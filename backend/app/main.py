import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

from . import data, llm  # noqa: E402  (env must be loaded before the LLM config is read)
from .models import AskRequest, AskResponse, ErrorResponse, SummaryResponse  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("spend_assistant")


@asynccontextmanager
async def lifespan(app: FastAPI):
    data.invoices()  # load and join the CSVs once at startup
    log.info("LLM path: %s", llm.llm_label())
    if llm.provider() == "stub":
        log.warning(llm.STUB_WARNING)
    yield


app = FastAPI(title="Finance spend intelligence assistant", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):517\d",
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(llm.LLMError)
async def llm_error_handler(request: Request, exc: llm.LLMError):
    log.error("ask failed: %s %s", exc.code, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})


@app.get("/summary", response_model=SummaryResponse)
def summary() -> dict:
    return data.get_summary()


@app.post(
    "/ask",
    response_model=AskResponse,
    responses={502: {"model": ErrorResponse}, 504: {"model": ErrorResponse}},
)
def ask(req: AskRequest) -> AskResponse:
    log.info("ask: %r", req.question)
    return llm.ask(req.question)
