FROM docker.io/yym68686/chatgpt:latest

EXPOSE 8080
ENTRYPOINT ["/bin/sh", "-c", "python3 -m http.server 8080 & python3 $(find / -name bot.py 2>/dev/null | head -n 1)"]
