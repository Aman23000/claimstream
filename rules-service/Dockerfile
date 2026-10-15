# Multi-stage build: compile + run unit tests with the JDK, ship only the JRE + jar
FROM eclipse-temurin:21-jdk AS build
WORKDIR /src
COPY src ./src
RUN javac -d out src/main/java/com/claimstream/rules/*.java src/test/java/com/claimstream/rules/*.java \
 && java -cp out com.claimstream.rules.RulesEngineTest \
 && jar --create --file rules-service.jar --main-class com.claimstream.rules.RulesServer -C out .

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=build /src/rules-service.jar .
EXPOSE 8090
HEALTHCHECK --interval=10s --timeout=2s CMD bash -c "exec 3<>/dev/tcp/127.0.0.1/8090" || exit 1
ENTRYPOINT ["java", "-XX:MaxRAMPercentage=75", "-jar", "rules-service.jar"]
