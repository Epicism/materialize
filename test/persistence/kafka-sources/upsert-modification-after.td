# Copyright Materialize, Inc. and contributors. All rights reserved.
#
# Use of this software is governed by the Business Source License
# included in the LICENSE file at the root of this repository.
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0.

$ set keyschema={
    "type": "record",
    "name": "Key",
    "fields": [
        {"name": "f1", "type": "long"}
    ]
  }

$ set schema={
        "type" : "record",
        "name" : "test",
        "fields" : [
            {"name":"f2", "type":"string"}
        ]
    }

# Update 5K records

$ kafka-ingest format=avro topic=upsert-modification key-format=avro key-schema=${keyschema} schema=${schema} start-iteration=2500 repeat=5000
{"f1": ${kafka-ingest.iteration}} {"f2": "a${kafka-ingest.iteration}"}

> SELECT COUNT(*), MIN(f1), MAX(f1) FROM upsert_modification_tbl;
10000 0 9999

> SELECT MIN(f1), MAX(f1), COUNT(*) FROM upsert_modification_tbl WHERE f2 LIKE 'a%';
2500 7499 5000

$ kafka-ingest format=bytes topic=textbytes key-format=bytes key-terminator=:
bírdmore:géese
mammalmore:moose
mammal1:
mammal1:mouse

> select * from texttext_tbl
key           text  kafka_partition  mz_offset
----------------------------------------------
fish          fish  0                0
bírdmore      géese 0                5
mammal1       mouse 0                8
mammalmore    moose 0                6

> select * from textbytes_tbl
key           data            kafka_partition  mz_offset
-------------------------------------------------------
fish          fish            0                0
bírdmore      g\xc3\xa9ese    0                5
mammal1       mouse           0                8
mammalmore    moose           0                6

> select * from bytestext_tbl
key             text  kafka_partition  mz_offset
------------------------------------------------
fish            fish  0                0
b\xc3\xadrdmore géese 0                5
mammal1         mouse 0                8
mammalmore      moose 0                6

> select * from bytesbytes_tbl
key                data            kafka_partition  mz_offset
-------------------------------------------------------------
fish               fish            0                0
b\xc3\xadrdmore    g\xc3\xa9ese    0                5
mammal1            mouse           0                8
mammalmore         moose           0                6
