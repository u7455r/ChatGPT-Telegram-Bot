FROM docker.io/yym68686/chatgpt:latest

EXPOSE 8080
CMD sh -c "python3 -m http.server 8080 & exec python3 /app/bot.py || exec python3 bot.py"
