from handlers import intent_router as ir


def test_build_classify_messages_has_system_and_user():
    msgs = ir.build_classify_messages("build me a form")
    assert msgs[0]["role"] == "system"
    assert "JSON" in msgs[0]["content"] or "json" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "build me a form"}


def test_parse_good_json():
    r = ir.parse_classification('{"intent":"build_app","confidence":0.9,"detail":"a form"}')
    assert (r.intent, r.detail) == ("build_app", "a form")
    assert r.confidence == 0.9


def test_parse_tolerates_code_fence_and_prose():
    raw = 'Sure!\n```json\n{"intent":"make_video","confidence":0.8,"detail":"x"}\n```'
    r = ir.parse_classification(raw)
    assert r.intent == "make_video"


def test_parse_unknown_intent_falls_back_to_question():
    r = ir.parse_classification('{"intent":"order_pizza","confidence":0.99}', fallback_detail="hi")
    assert r.intent == "question" and r.confidence == 0.0 and r.detail == "hi"


def test_parse_garbage_falls_back():
    r = ir.parse_classification("not json at all", fallback_detail="orig")
    assert r.intent == "question" and r.detail == "orig"


def test_parse_clamps_confidence():
    assert ir.parse_classification('{"intent":"build_app","confidence":5}').confidence == 1.0


def test_decide_question_is_answer():
    assert ir.decide(ir.IntentResult("question", 0.9, "x")).kind == "answer"


def test_decide_low_confidence_is_answer():
    assert ir.decide(ir.IntentResult("build_app", 0.3, "x")).kind == "answer"


def test_decide_build_is_confirm():
    a = ir.decide(ir.IntentResult("build_app", 0.8, "a form"))
    assert a.kind == "confirm" and a.intent == "build_app" and a.detail == "a form"


def test_decide_other_actionable_is_suggest():
    assert ir.decide(ir.IntentResult("make_video", 0.8, "x")).kind == "suggest"


def test_decide_daily_briefing_is_confirm():
    assert ir.decide(ir.IntentResult("daily_briefing", 0.9, "x")).kind == "confirm"


def test_decide_schedule_task_is_confirm():
    r = ir.IntentResult("schedule_task", 0.9, "x", when="every morning", task="summarize email")
    assert ir.decide(r).kind == "confirm"


def test_parse_reads_when_and_task():
    r = ir.parse_classification(
        '{"intent":"schedule_task","confidence":0.9,"detail":"d",'
        '"when":"every morning at 8am","task":"summarize my emails"}')
    assert r.intent == "schedule_task"
    assert r.when == "every morning at 8am"
    assert r.task == "summarize my emails"


class _FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    async def chat_completion(self, messages, model):
        return self._reply


async def test_classify_happy_path():
    llm = _FakeLLM('{"intent":"build_app","confidence":0.9,"detail":"a form"}')
    r = await ir.classify("build me a form", llm, "m")
    assert r.intent == "build_app"


async def test_classify_empty_reply_is_question():
    r = await ir.classify("hi", _FakeLLM(""), "m")
    assert r.intent == "question"


class _BoomLLM:
    async def chat_completion(self, messages, model):
        raise RuntimeError("down")


async def test_classify_model_error_is_question():
    r = await ir.classify("anything", _BoomLLM(), "m")
    assert r.intent == "question" and r.detail == "anything"
