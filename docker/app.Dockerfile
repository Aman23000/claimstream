# One Python image for api / processor / producer / dashboard / batch jobs (command set in compose)
FROM python:3.15-slim
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
    && rm -rf /var/lib/apt/lists/*          # Java is needed by PySpark
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt
COPY claimstream ./claimstream
COPY dashboard ./dashboard
COPY sql ./sql
COPY .streamlit ./.streamlit
ENV PYTHONUNBUFFERED=1
RUN useradd -m app && mkdir -p /app/data && chown -R app /app
USER app
CMD ["uvicorn", "claimstream.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
