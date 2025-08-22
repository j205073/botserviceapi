from quart import Quart, jsonify
import os

app = Quart(__name__)

@app.route("/ping", methods=["GET"])
async def ping():
    return jsonify({"status": "ok", "message": "服務正常運作"})

@app.route("/api/test", methods=["GET"])
async def test():
    return jsonify({
        "status": "success",
        "environment": {
            "AZURE_OPENAI_ENDPOINT": bool(os.getenv("AZURE_OPENAI_ENDPOINT")),
            "AZURE_OPENAI_API_KEY": bool(os.getenv("AZURE_OPENAI_API_KEY")),
            "MS_APP_ID": bool(os.getenv("MS_APP_ID"))
        }
    })

if __name__ == "__main__":
    import hypercorn.asyncio
    import hypercorn.config
    
    config = hypercorn.config.Config()
    config.bind = ["0.0.0.0:8000"]
    import asyncio
    asyncio.run(hypercorn.asyncio.serve(app, config))