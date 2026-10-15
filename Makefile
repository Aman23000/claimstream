.PHONY: install data bootstrap train batch forecast pipeline rules up stop test test-all screenshots docker-up docker-down

install:            ## Python deps
	pip install -r requirements.txt

data:               ## download the real policy / claim-amount data
	python -m claimstream.ingest.download

rules:              ## compile, unit-test and package the Java rules service
	cd rules-service && javac -d out src/main/java/com/claimstream/rules/*.java src/test/java/com/claimstream/rules/*.java \
	 && java -cp out com.claimstream.rules.RulesEngineTest \
	 && jar --create --file rules-service.jar --main-class com.claimstream.rules.RulesServer -C out .

bootstrap:          ## schema + policies + 2 years of claim history (Postgres + Parquet lake)
	python -m claimstream.ingest.bootstrap

train:              ## fraud model (needs the rules service running for the rules baseline)
	python -m claimstream.ml.train_fraud

batch:              ## Spark bronze -> gold
	python -m claimstream.batch.spark_daily

forecast:           ## LSTM vs SARIMA vs naive + 30-day forecast
	python -m claimstream.ml.train_forecast

pipeline: data bootstrap train batch forecast

up:                 ## run the whole stack locally (no Docker)
	scripts/run_local.sh start

stop:
	scripts/run_local.sh stop

test:               ## unit tests (no services needed)
	pytest -q -m "not integration"

test-all:           ## unit + integration (stack must be up)
	pytest -q

screenshots:
	python scripts/screenshots.py

docker-up:
	docker compose up --build -d

docker-down:
	docker compose down -v
