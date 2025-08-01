# Copyright Materialize, Inc. and contributors. All rights reserved.
#
# Use of this software is governed by the Business Source License
# included in the LICENSE file at the root of this repository.
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0.

"""
Test cluster isolation by introducing faults of various kinds in cluster1 and
then making sure that cluster2 continues to operate properly
"""

from collections.abc import Callable
from dataclasses import dataclass

from materialize.mzcompose.composition import (
    Composition,
    Service,
    WorkflowArgumentParser,
)
from materialize.mzcompose.services.clusterd import Clusterd
from materialize.mzcompose.services.kafka import Kafka
from materialize.mzcompose.services.materialized import Materialized
from materialize.mzcompose.services.schema_registry import SchemaRegistry
from materialize.mzcompose.services.testdrive import Testdrive
from materialize.mzcompose.services.zookeeper import Zookeeper
from materialize.ui import UIError
from materialize.util import selected_by_name

SERVICES = [
    Zookeeper(),
    Kafka(),
    SchemaRegistry(),
    # We use mz_panic() in some test scenarios, so environmentd must stay up.
    Materialized(
        propagate_crashes=False,
        additional_system_parameter_defaults={
            "unsafe_enable_unsafe_functions": "true",
            "unsafe_enable_unstable_dependencies": "true",
        },
        support_external_clusterd=True,
    ),
    Clusterd(name="clusterd_1_1"),
    Clusterd(name="clusterd_1_2"),
    Clusterd(name="clusterd_2_1"),
    Clusterd(name="clusterd_2_2"),
    Testdrive(),
]


@dataclass
class Disruption:
    name: str
    disruption: Callable


disruptions = [
    Disruption(
        name="pause-one-cluster",
        disruption=lambda c: c.pause("clusterd_1_1"),
    ),
    Disruption(
        name="kill-all-clusters",
        disruption=lambda c: c.kill("clusterd_1_1", "clusterd_1_2"),
    ),
    Disruption(
        name="pause-in-materialized-view",
        disruption=lambda c: c.testdrive(
            """
> SET cluster=cluster1

> CREATE TABLE sleep_table (sleep INTEGER);

> CREATE MATERIALIZED VIEW sleep_view AS SELECT mz_unsafe.mz_sleep(sleep) FROM sleep_table;

> INSERT INTO sleep_table SELECT 1200 FROM generate_series(1,32)
""",
        ),
    ),
    Disruption(
        name="drop-cluster",
        disruption=lambda c: c.testdrive(
            """
> DROP CLUSTER cluster1 CASCADE
""",
        ),
    ),
    Disruption(
        name="panic-in-insert-select",
        disruption=lambda c: c.testdrive(
            """
> SET cluster=cluster1
> SET statement_timeout='1s'

> CREATE TABLE panic_table (f1 TEXT);

> INSERT INTO panic_table VALUES ('forced panic');

! INSERT INTO panic_table SELECT mz_unsafe.mz_panic(f1) FROM panic_table;
contains: statement timeout
""",
        ),
    ),
]


def workflow_default(c: Composition, parser: WorkflowArgumentParser) -> None:

    parser.add_argument("disruptions", nargs="*", default=[d.name for d in disruptions])

    args = parser.parse_args()

    c.up("zookeeper", "kafka", "schema-registry")
    for id, disruption in enumerate(selected_by_name(args.disruptions, disruptions)):
        run_test(c, disruption, id)


def populate(c: Composition) -> None:
    # Create some database objects
    c.testdrive(
        """
> SET cluster=cluster1

> DROP TABLE IF EXISTS t1 CASCADE;

> CREATE TABLE t1 (f1 TEXT);

> INSERT INTO t1 VALUES (1), (2);

> CREATE VIEW v1 AS SELECT COUNT(*) AS c1 FROM t1;

> CREATE DEFAULT INDEX i1 IN CLUSTER cluster2 ON v1;
""",
    )


def validate(c: Composition) -> None:
    # Validate that cluster2 continues to operate
    c.testdrive(
        """
# Dataflows

$ set-regex match=\\d{13} replacement=<TIMESTAMP>

> SET cluster=cluster2

> SELECT * FROM v1;
2

# Tables

> INSERT INTO t1 VALUES (3);

> SELECT * FROM t1;
1
2
3

# Introspection tables

> SELECT name FROM (SHOW CLUSTERS LIKE 'cluster2')
cluster2

> SELECT name FROM mz_tables WHERE name = 't1';
t1

# DDL statements

> CREATE MATERIALIZED VIEW v2 AS SELECT COUNT(*) AS c1 FROM t1;

> SELECT * FROM v2;
3

> CREATE MATERIALIZED VIEW v1mat AS SELECT * FROM v1;

> CREATE INDEX i2 IN CLUSTER cluster2 ON t1 (f1);

> SELECT f1 FROM t1;
1
2
3

# Tables

> CREATE TABLE t2 (f1 INTEGER);

> INSERT INTO t2 VALUES (1);

> INSERT INTO t2 SELECT * FROM t2;

> SELECT * FROM t2;
1
1

# Sources

# Explicitly set a progress topic to ensure multiple runs (which the
# mzcompose.py driver does) do not clash.
# TODO: remove this once we add some form of nonce to the default progress
# topic name.
> CREATE CONNECTION IF NOT EXISTS kafka_conn TO KAFKA (
    BROKER '${testdrive.kafka-addr}',
    PROGRESS TOPIC 'testdrive-progress-${testdrive.seed}',
    SECURITY PROTOCOL PLAINTEXT
  );

> CREATE CONNECTION IF NOT EXISTS csr_conn TO CONFLUENT SCHEMA REGISTRY (
    URL '${testdrive.schema-registry-url}'
  );

$ kafka-create-topic topic=source1 partitions=1
$ kafka-ingest format=bytes topic=source1
A

> CREATE SOURCE source1
  FROM KAFKA CONNECTION kafka_conn (TOPIC 'testdrive-source1-${testdrive.seed}')

> CREATE TABLE source1_tbl FROM SOURCE source1 (REFERENCE "testdrive-source1-${testdrive.seed}")
  FORMAT BYTES

> SELECT * FROM source1_tbl
A

# TODO: This should be made reliable without sleeping, database-issues#7611
$ sleep-is-probably-flaky-i-have-justified-my-need-with-a-comment duration=5s

# Sinks
> CREATE SINK sink1 FROM v1mat
  INTO KAFKA CONNECTION kafka_conn (TOPIC 'sink1')
  FORMAT AVRO USING CONFLUENT SCHEMA REGISTRY CONNECTION csr_conn
  ENVELOPE DEBEZIUM

$ kafka-verify-data format=avro sink=materialize.public.sink1 sort-messages=true
{"before": null, "after": {"row":{"c1": 3}}}
""",
    )


def run_test(c: Composition, disruption: Disruption, id: int) -> None:
    print(f"+++ Running disruption scenario {disruption.name}")

    with c.override(
        Testdrive(
            no_reset=True,
            materialize_params={"cluster": "cluster2"},
            seed=id,
        ),
        Clusterd(
            name="clusterd_1_1",
            process_names=["clusterd_1_1", "clusterd_1_2"],
        ),
        Clusterd(
            name="clusterd_1_2",
            process_names=["clusterd_1_1", "clusterd_1_2"],
        ),
        Clusterd(
            name="clusterd_2_1",
            process_names=["clusterd_2_1", "clusterd_2_2"],
        ),
        Clusterd(
            name="clusterd_2_2",
            process_names=["clusterd_2_1", "clusterd_2_2"],
        ),
    ):
        c.up(
            "materialized",
            "clusterd_1_1",
            "clusterd_1_2",
            "clusterd_2_1",
            "clusterd_2_2",
            Service("testdrive", idle=True),
        )

        c.sql(
            "ALTER SYSTEM SET unsafe_enable_unorchestrated_cluster_replicas = true;",
            port=6877,
            user="mz_system",
        )

        c.sql(
            """
            DROP CLUSTER IF EXISTS cluster1 CASCADE;
            CREATE CLUSTER cluster1 REPLICAS (replica1 (
                STORAGECTL ADDRESSES ['clusterd_1_1:2100', 'clusterd_1_2:2100'],
                STORAGE ADDRESSES ['clusterd_1_1:2103', 'clusterd_1_2:2103'],
                COMPUTECTL ADDRESSES ['clusterd_1_1:2101', 'clusterd_1_2:2101'],
                COMPUTE ADDRESSES ['clusterd_1_1:2102', 'clusterd_1_2:2102']
            ));
            """
        )

        c.sql(
            """
            DROP CLUSTER IF EXISTS cluster2 CASCADE;
            CREATE CLUSTER cluster2 REPLICAS (replica1 (
                STORAGECTL ADDRESSES ['clusterd_2_1:2100', 'clusterd_2_2:2100'],
                STORAGE ADDRESSES ['clusterd_2_1:2103', 'clusterd_2_2:2103'],
                COMPUTECTL ADDRESSES ['clusterd_2_1:2101', 'clusterd_2_2:2101'],
                COMPUTE ADDRESSES ['clusterd_2_1:2102', 'clusterd_2_2:2102']
            ));
            """
        )

        populate(c)

        # Disrupt cluster1 by some means
        disruption.disruption(c)

        validate(c)

    cleanup_list = [
        "materialized",
        "testdrive",
        "clusterd_1_1",
        "clusterd_1_2",
        "clusterd_2_1",
        "clusterd_2_2",
    ]
    try:
        c.kill(*cleanup_list)
    except UIError as e:
        print(e)
        # Killing multiple clusterds from the same cluster may fail
        # as the second clusterd may have already exited after the first
        # one was killed, due to the 'shared-fate' mechanism.
        pass

    c.rm(*cleanup_list, destroy_volumes=True)

    c.rm_volumes("mzdata")
