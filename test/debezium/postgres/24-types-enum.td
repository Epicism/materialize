# Copyright Materialize, Inc. and contributors. All rights reserved.
#
# Use of this software is governed by the Business Source License
# included in the LICENSE file at the root of this repository.
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0.

#
# Make sure that the ENUM type is replicated correctly
#

$ postgres-execute connection=postgres://postgres:postgres@postgres
CREATE TYPE enum1 AS ENUM ('val1', 'val2');
CREATE TABLE enum_type ( f1 enum1, f2 INTEGER PRIMARY KEY);
INSERT INTO enum_type VALUES ('val1', 0), ('val2', 1);

$ schema-registry-wait topic=postgres.public.enum_type

> CREATE CONNECTION IF NOT EXISTS csr_conn TO CONFLUENT SCHEMA REGISTRY (
    URL '${testdrive.schema-registry-url}'
  );

> CREATE CONNECTION IF NOT EXISTS kafka_conn TO KAFKA (BROKER '${testdrive.kafka-addr}', SECURITY PROTOCOL PLAINTEXT);

> CREATE SOURCE enum_type
  FROM KAFKA CONNECTION kafka_conn (TOPIC 'postgres.public.enum_type');

> CREATE TABLE enum_type_tbl FROM SOURCE enum_type (REFERENCE "postgres.public.enum_type")
  FORMAT AVRO USING CONFLUENT SCHEMA REGISTRY CONNECTION csr_conn
  ENVELOPE DEBEZIUM;

> SELECT pg_typeof(f1), f1 FROM enum_type_tbl;
text val1
text val2
