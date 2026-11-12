FROM docker.io/yym68686/chatgpt:latest

CMD sh -c "python3 -m http.server ${PORT:-8080} & python3 bot.py"
