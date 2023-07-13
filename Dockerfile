FROM nimlang/nim:alpine
WORKDIR /morphysm
COPY requirements.txt .
RUN apk add git python3 \
 && python3 -m ensurepip \
 && python3 -m pip install --no-cache-dir -r requirements.txt
COPY main.py /morphysm/main.py
ENTRYPOINT ["python3", "/morphysm/main.py"]
