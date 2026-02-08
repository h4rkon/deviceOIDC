FROM debezium/connect:2.5

ARG CONNECT_VERSION=0.6.19
ARG CONNECT_URL=https://github.com/databricks/iceberg-kafka-connect/releases/download/v${CONNECT_VERSION}/iceberg-kafka-connect-runtime-${CONNECT_VERSION}.zip

RUN mkdir -p /kafka/connect/iceberg \
    && curl -fsSL "$CONNECT_URL" -o /tmp/iceberg.zip \
    && unzip -q /tmp/iceberg.zip -d /kafka/connect/iceberg \
    && rm /tmp/iceberg.zip
