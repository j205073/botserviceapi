from flask import Flask, request, jsonify

app = Flask(__name__)


@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "ok", "message": "Bot is alive"})
