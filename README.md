# Build (*Run on remote server*)
docker build -t models-api-bot:<version> .

# Run (*Run on remote server*)
docker run -d --restart unless-stopped --name models-api-bot models-api-bot:<version>

# TODO
- [x] - Админ по команде может обновить excel файл. По умолчанию этот файл уже лежит на сервере. Содержимое этого файла прикладывается к запросу "Скаунтинг стартапов"
