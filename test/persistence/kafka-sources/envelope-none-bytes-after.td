# Copyright Materialize, Inc. and contributors. All rights reserved.
#
# Use of this software is governed by the Business Source License
# included in the LICENSE file at the root of this repository.
#
# As of the Change Date specified in that file, in accordance with
# the Business Source License, use of this software will be governed
# by the Apache License, Version 2.0.

> SELECT COUNT(*) FROM envelope_none_text_tbl;
10000

> SELECT COUNT(*) FROM envelope_none_bytes_tbl;
10000

$ kafka-ingest topic=envelope-none-bytes format=bytes repeat=5000
ABC
XYZ

$ kafka-ingest topic=envelope-none-text format=bytes repeat=5000
ABC
XYZ

> SELECT COUNT(*), COUNT(DISTINCT data) FROM envelope_none_bytes_tbl;
20000 2

> SELECT COUNT(*), COUNT(DISTINCT "text") FROM envelope_none_text_tbl;
20000 2
