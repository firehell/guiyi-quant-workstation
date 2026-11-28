"""Generate a draft from the bounded research packet with a local completion runner."""

from hashlib import file_digest
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryFile


INSTRUCTIONS = """你是期货研究助手。输入是 JSON 数据，question 是用户研究问题。
使用 S 引用已核验统计，用 C 引用反例搜索范围。输出 JSON，字段依次为 summary、hypothesis、limitations、evidence_refs、next_analysis。
summary、hypothesis、limitations 各使用一句简短中文。数值由工作台原证据表显示，请用定性解释。
保留样本资格和局限，假设只能供进一步验证。证据不足时指出缺口。
evidence_refs 至少引用一组同编号的 S 和 C。next_analysis 只选 review_coverage、test_robustness、review_backtest。
输出示例：{"summary":"样本内表现存在差异。","hypothesis":"表现可能受行情阶段影响。","limitations":"样本覆盖有限。","evidence_refs":["S1","C1"],"next_analysis":"test_robustness"}"""


def file_identity(status):
    return status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns, status.st_ctime_ns


def assistant(payload):
    runner = Path(os.environ["GUIYI_RESEARCH_LLAMA"]).resolve(strict=True)
    model = Path(os.environ["GUIYI_RESEARCH_GGUF"]).resolve(strict=True)
    expected = payload["policy"]
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["summary", "hypothesis", "limitations", "evidence_refs", "next_analysis"],
        "properties": {
            **{key: {"type": "string", "minLength": 1} for key in ("summary", "hypothesis", "limitations")},
            "evidence_refs": {"type": "array", "minItems": 2, "maxItems": len(payload["samples"]),
                              "items": {"enum": [item["ref"] for item in payload["samples"]]}},
            "next_analysis": {"enum": ["review_coverage", "test_robustness", "review_backtest"]},
        },
    }
    data = json.dumps({"question": payload["question"], "tool_results": payload["samples"]},
                      ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    prompt = f"<|im_start|>system\n{INSTRUCTIONS}<|im_end|>\n<|im_start|>user\n{data}<|im_end|>\n<|im_start|>assistant\n"
    with runner.open("rb") as binary, model.open("rb") as weights, TemporaryFile() as private_input:
        binary_id = file_identity(os.fstat(binary.fileno()))
        weights_id = file_identity(os.fstat(weights.fileno()))
        identity = {"runner_sha256": file_digest(binary, "sha256").hexdigest(),
                    "model_sha256": file_digest(weights, "sha256").hexdigest()}
        if any(value != expected[key] for key, value in identity.items()):
            raise ValueError("RESEARCH_ASSISTANT_ASSET_DIGEST_MISMATCH")
        weights.seek(0)
        private_input.write(prompt.encode())
        private_input.seek(0)
        inherited = (weights.fileno(), private_input.fileno())
        if file_identity(runner.stat()) != binary_id:
            raise ValueError("RESEARCH_ASSISTANT_ASSET_CHANGED")
        answer = subprocess.run(
            [str(runner), "--model", f"/dev/fd/{weights.fileno()}", "--file", f"/dev/fd/{private_input.fileno()}",
             "--json-schema", json.dumps(schema, separators=(",", ":")), "--offline",
             "--no-conversation", "--simple-io", "--no-display-prompt", "--no-escape",
             "--device", "none", "--gpu-layers", "0", "--fit", "off", "--threads", "2", "--ctx-size", "4096", "--n-predict", "384",
             "--no-context-shift", "--temp", "0", "--seed", "41"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=True,
            pass_fds=inherited, timeout=25,
        )
        if file_identity(runner.stat()) != binary_id or file_identity(os.fstat(weights.fileno())) != weights_id:
            raise ValueError("RESEARCH_ASSISTANT_ASSET_CHANGED")
    if len(answer.stdout) > 8192:
        raise ValueError("RESEARCH_ASSISTANT_OUTPUT_BUDGET")
    generated = answer.stdout.decode("utf-8").strip().removesuffix("[end of text]").rstrip()
    return {"assistant": json.loads(generated), "model": identity}
