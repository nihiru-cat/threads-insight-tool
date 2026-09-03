"""AI-based content safety check for a generated post draft.

Checks the four violation types that need language understanding (see
app.schemas.safety). Excessive similarity to the source post and
mass-duplicate generation are checked separately in
app.services.generation_service via app.services.similarity — those are
structural comparisons, not judgments an AI needs to make.
"""

from __future__ import annotations

import logging

from app.services.ai.base import AIClient
from app.services.ai.json_utils import call_and_validate
from app.schemas.safety import SafetyCheckResult

SYSTEM_PROMPT = """\
あなたは占い・スピリチュアル系のThreads投稿案を審査するコンテンツセーフティ担当者です。
与えられた投稿案本文が、以下4種類の問題のいずれかに該当するか判定してください。

- personal_attack: 特定個人・特定人物像への攻撃・誹謗中傷
- medical_legal_financial_claim: 医療・法律・金融について断定的な助言や保証をしている
  （例: 「この方法で必ず病気が治る」「絶対に儲かる」など、専門家の判断を要する事項の断定）
- exaggerated_guarantee: 「絶対に当たる」「100%叶う」など、科学的・論理的根拠のない誇大な断定表現
- fear_mongering: 読者の不安を過度に煽り、恐怖によって行動を強制するような表現
  （軽度の警告や一般的な注意喚起は該当しない。読者を過度に不安にさせ判断力を奪うような煽りのみ該当）

該当する問題がなければ is_safe=true, violations=[] としてください。
該当する問題があれば is_safe=false とし、violations に該当する項目名（上記の識別子）をすべて含めてください。
reason には判定理由を具体的に記載してください。

出力は次のキーのみを持つJSONオブジェクトにしてください: is_safe, violations, reason
説明文・前置き・Markdownのコードフェンスは一切付けず、JSONオブジェクトのみを出力してください。
"""


def build_user_prompt(generated_text: str) -> str:
    return f"投稿案本文:\n{generated_text}\n"


def check_safety(
    client: AIClient,
    generated_text: str,
    max_parse_retries: int = 2,
    logger: logging.Logger | None = None,
    log_context: str = "",
) -> SafetyCheckResult:
    """Run the safety check. Raises AIError on failure (network or
    unparseable response) — the caller (generation_service) decides how to
    treat that (currently: treat as a failed attempt, same as a rejection).
    """
    log = logger or logging.getLogger("threads_tool")
    return call_and_validate(
        client,
        SYSTEM_PROMPT,
        build_user_prompt(generated_text),
        SafetyCheckResult,
        max_parse_retries=max_parse_retries,
        logger=log,
        log_context=log_context,
    )
