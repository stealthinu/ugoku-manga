# CPU image: pipeline, web UI and the dummy video backend. Models are downloaded at run time into /models (a volume), not baked in.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml LICENSE NOTICE.md README.md ./
COPY ugoku ./ugoku
RUN pip install --no-cache-dir ".[server]"
ENV UGOKU_MODEL_DIR=/models UGOKU_CACHE=/cache
VOLUME ["/models", "/data", "/cache"]
EXPOSE 8771
# the UI has no login: publish the port only on a trusted network
CMD ["ugoku", "serve", "--host", "0.0.0.0", "--public", "--data", "/data"]
