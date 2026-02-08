FROM debezium/connect:2.5

ARG CONNECT_VERSION=0.6.19
ARG CONNECT_URL=https://github.com/databricks/iceberg-kafka-connect/releases/download/v${CONNECT_VERSION}/iceberg-kafka-connect-runtime-${CONNECT_VERSION}.zip
ARG COMMONS_CONF2_VERSION=2.9.0
ARG HADOOP_COMMON_VERSION=3.3.4
ARG HADOOP_AUTH_VERSION=3.3.4
ARG HADOOP_AWS_VERSION=3.3.4
ARG AWS_SDK_BUNDLE_VERSION=1.11.1026

RUN mkdir -p /kafka/connect/iceberg \
    && curl -fsSL "$CONNECT_URL" -o /tmp/iceberg.zip \
    && unzip -q /tmp/iceberg.zip -d /kafka/connect/iceberg \
    && rm /tmp/iceberg.zip \
    && curl -fsSL "https://repo1.maven.org/maven2/org/apache/commons/commons-configuration2/${COMMONS_CONF2_VERSION}/commons-configuration2-${COMMONS_CONF2_VERSION}.jar" \
      -o /kafka/connect/iceberg/commons-configuration2-${COMMONS_CONF2_VERSION}.jar \
    && curl -fsSL "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-common/${HADOOP_COMMON_VERSION}/hadoop-common-${HADOOP_COMMON_VERSION}.jar" \
      -o /kafka/connect/iceberg/hadoop-common-${HADOOP_COMMON_VERSION}.jar \
    && curl -fsSL "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-auth/${HADOOP_AUTH_VERSION}/hadoop-auth-${HADOOP_AUTH_VERSION}.jar" \
      -o /kafka/connect/iceberg/hadoop-auth-${HADOOP_AUTH_VERSION}.jar \
    && curl -fsSL "https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/${HADOOP_AWS_VERSION}/hadoop-aws-${HADOOP_AWS_VERSION}.jar" \
      -o /kafka/connect/iceberg/hadoop-aws-${HADOOP_AWS_VERSION}.jar \
    && curl -fsSL "https://repo1.maven.org/maven2/com/amazonaws/aws-java-sdk-bundle/${AWS_SDK_BUNDLE_VERSION}/aws-java-sdk-bundle-${AWS_SDK_BUNDLE_VERSION}.jar" \
      -o /kafka/connect/iceberg/aws-java-sdk-bundle-${AWS_SDK_BUNDLE_VERSION}.jar
