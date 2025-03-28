FROM python:3.11

ENV PYTHONFAULTHANDLER=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random
ENV PYTHONDONTWRITEBYTECODE 1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV PIP_DEFAULT_TIMEOUT=100

RUN apt-get update

COPY requirements.txt requirements.txt
RUN pip3 install -r requirements.txt
COPY . .

RUN chmod +x ./src/bot.py
CMD ["python", "./src/bot.py"]
