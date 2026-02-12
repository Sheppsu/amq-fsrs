from amq import AMQClient
import training
from contextlib import asynccontextmanager
from pydantic import BaseModel
import os
import logging
import asyncio
import dotenv

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

logging.basicConfig(
    format='%(asctime)s %(name)s [%(levelname)s]: %(message)s',
    level=logging.INFO,
)
log = logging.getLogger(__name__)

dotenv.load_dotenv()

log.info("Loading fsrs trainer...")
trainer = training.Trainer.from_path("fsrs.json")
log.info("Loaded fsrs trainer")
amq_client: AMQClient = AMQClient(os.getenv("AMQ_USERNAME"), trainer)


async def run_amq_client():
    log.info("Logging into AMQ...")
    if not await amq_client.login(os.getenv("AMQ_PASSWORD")):
        return
    log.info("Connecting to AMQ server...")
    if not await amq_client.connect():
        return
    log.info("Successfully connected to AMQ server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_amq_client())
    yield
    await amq_client.close()
    task.cancel()
    await task


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def home():
    return FileResponse(os.path.join("pages", "index.html"))


@app.get("/next")
async def info():
    if not trainer.is_ready:
        return Response(status_code=500)
    ann_song_id = trainer.get_next_song()
    result = await amq_client.get_song_info(ann_song_id)
    return {
        "song": result,
        "answers": trainer.get_valid_answers(result["songId"])
    }


@app.get("/anime")
async def anime():
    if not trainer.is_ready:
        return Response(status_code=500)
    return trainer.get_all_anime()


class Answer(BaseModel):
    answer_time: int | None


@app.post("/answer")
async def save(answer: Answer):
    if not trainer.is_ready:
        return Response(status_code=500)
    trainer.save_result(answer.answer_time)
    return "OK"


@app.get("/song-info/{song_id}")
async def song_info(song_id: int):
    if not trainer.is_ready:
        return Response(status_code=500)
    return trainer.get_song_info(song_id)


@app.get("/ann-song-info/{ann_song_id}")
async def ann_song_info(ann_song_id: int):
    if not trainer.is_ready:
        return Response(status_code=500)
    return trainer.get_ann_song_info(ann_song_id)


@app.get("/schedule-info")
async def schedule_info():
    if not trainer.is_ready:
        return Response(status_code=500)
    return trainer.get_schedule_info()
