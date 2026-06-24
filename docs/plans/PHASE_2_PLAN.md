# Phase 2 — Adapter Contracts, Model Gateway & Test Doubles

> **Context (vì sao có kế hoạch này)**
> Phase 1 đã `COMPLETED` và merge vào `develop` (commit `3222300`; baseline sạch, 128 test PASS, gate 5/5). ROADMAP §7 quy định adapter layer đứng **sau** persistence (Phase 1) và **trước** execution boundary (Phase 3). Phase 2 dựng ranh giới adapter **provider-neutral, asynchronous** + một gateway model thật tối thiểu (LiteLLM), để các phase sau gọi được cloud/local model qua một contract thống nhất mà **không** để core/domain phụ thuộc provider hay LiteLLM.
>
> Đây là **tài liệu kế hoạch** (không phải production code). Bản kế hoạch này được PO duyệt (APPROVED TO IMPLEMENT) kèm sáu hiệu chỉnh cuối (§3). Implement theo sáu checkpoint §6, mỗi checkpoint là một nhiệm vụ review độc lập.

---

## 1. Trạng thái và mục tiêu

- **Trạng thái:** Phase 1 `COMPLETED`; Phase 2 `NOT_STARTED` → bắt đầu. Branch triển khai: `phase/2-adapters` (từ `develop`@`3222300`).
- **Mục tiêu (ROADMAP §8 Phase 2):** ranh giới adapter provider-neutral + gateway thật tối thiểu, không xây mọi provider.
- **Ranh giới cốt lõi:** Phase 2 **không** phải orchestration. Chỉ gồm: contract adapter (LLM + tool) + LiteLLM gateway (OpenAI bootstrap) + Ollama adapter + test doubles + config/secret/timeout nền tảng. **Không** enforcement bảo mật (Phase 3), **không** energy/persist usage (Phase 3), **không** LangGraph/worker/loop (Phase 4–6).

---

## 2. Nguồn sự thật authoritative

| Nguồn | Ràng buộc rút ra |
|---|---|
| `ROADMAP.md` §8 Phase 2 (260–302) | Scope: `LLMAdapter` interface; 1 cloud thật (qua config) + 1 Ollama thật + mock; tool adapter = contract; LiteLLM không lộ type; phân biệt risk model vs execution |
| `ROADMAP.md` §13.1 | Cloud provider chọn qua config; không frozen bằng roadmap. **PO chốt: OpenAI là bootstrap provider** |
| `ADAPTER_CONTRACT.md` §4/§8/§9/§10/§11 | `complete(request)->response`; timeout bắt buộc; structured error; usage logging; adapter selection metadata |
| `ADR-0003` (Accepted) | LiteLLM = gateway; không để worker gọi SDK trực tiếp; ghi usage metadata |
| `ADR-0004` (Accepted) | Ollama local-first; model coding local (Qwen Coder); cần retry/escalation (P6) |
| `pyproject.toml` / `scripts/quality/gate.py` | mypy strict, ruff, file ≤350; gate = ruff-lint/format + mypy(`src scripts`) + file-size + pytest |
| Phase 1 code | Port pattern = Protocol + port-owned error (rooted `AntError`); value objects `TokenCount`/`UtcTimestamp`; DI root `cli/composition.py`; AST `test_import_boundary.py` |

**Chênh lệch ghi nhận (không sửa doc frozen):** `ADAPTER_CONTRACT.md` (Draft v0.1) mô tả `complete` **synchronous** và có `context_package` trong request. Phase 2 hiện thực **async** (PO chỉ đạo) và **bỏ** `context_package` (thuộc Phase 3B). Chênh lệch này ghi ở completion report; nâng/đổi `ADAPTER_CONTRACT` cần ADR riêng + PO.

---

## 3. Sáu hiệu chỉnh cuối của PO (ghi đè revised plan)

1. **Cloud adapter provider-neutral:** đặt tên `LiteLLMCloudAdapter` (KHÔNG `OpenAiCloudAdapter`). OpenAI chỉ là bootstrap provider chọn qua config/live verification; Anthropic/Gemini sau này dùng cùng adapter. Provider/model không hard-code trong class; type LiteLLM/OpenAI không rò khỏi infrastructure adapter. `OllamaAdapter` vẫn là class riêng (local endpoint/capability/error khác). *Ảnh hưởng từ CP3; CP1 chỉ đảm bảo public contract không chứa assumption OpenAI-specific.*
2. **Timeout policy (float, thống nhất toàn Phase 2):** mọi timeout là `float` để khớp trực tiếp `LLMRequest.timeout_seconds: float | None` (CP3 dùng output resolver as-is, không convert). Precedence `request > endpoint/model config > system default`. Reject: `bool`, `NaN`, `±inf`, `<= 0`, `> MAX_TIMEOUT_SECONDS`; **không clamp**, không round, không ép về int; không hard-code trong adapter. Config `timeout_seconds: 60` (int) và `60.5` (float) đều normalize thành float. *CP1 định nghĩa field; resolution logic ở CP2.*
3. **Async bridge:** `LLMAdapter` async. **Không** thêm `asyncio.run` demo vào production composition root (composition chỉ wiring dependency). `asyncio.run` chỉ ở synchronous entry point thật hoặc live/test script. CP6 không tạo dead bridge code (Phase 2 chưa có CLI command gọi model).
4. **SecretProvider semantics:** `get(name: str) -> str | None`; trả `None` khi không tồn tại hoặc rỗng; **không tạo `SecretError`** chỉ để biểu diễn missing secret (absence không phải lỗi); factory/cloud adapter chuyển missing secret thành `AdapterAuthenticationError` (CP3/CP6); không vừa return None vừa raise cùng trường hợp; không log/representation chứa secret. *Triển khai CP2; CP1 error taxonomy đã có authentication error đúng nghĩa.*
5. **Model configuration:** model không hard-code, không là domain constant; config cũ không có `models` vẫn load; invocation khi model/endpoint chưa cấu hình → structured configuration/invalid-request error; không tự chọn model ngầm; sample config + live verification cung cấp model cụ thể.
6. **Fake/test doubles ngoài production package:** `tests/contracts/llm_contract.py` + `tests/support/fake_llm.py`. Không đặt `FakeLLMAdapter` trong `src/ant_orchestrator` (trừ khi có runtime use case tài liệu hóa). Fake không vào production factory/config, không kéo LiteLLM vào import graph, chỉ phục vụ automated tests.

---

## 4. Kiến trúc đề xuất (module mới, SRP, mỗi file < 350 dòng)

```
src/ant_orchestrator/
├── application/ports/
│   ├── llm.py            # LLMAdapter Protocol (async complete) + DTO:
│   │                     #   LLMRequest, LLMMessage, MessageRole, LLMResponse,
│   │                     #   ModelUsage, UsageStatus, FinishReason,
│   │                     #   AdapterIdentity, AdapterCapabilities  (KHÔNG cost)
│   ├── llm_errors.py     # AdapterError(AntError) + 7 subclass + AdapterErrorCode + retryable
│   ├── filesystem.py     # [CP5] FileSystemAdapter Protocol + DTO + error
│   ├── shell.py          # [CP5] ShellAdapter + ShellRequest/Response + error
│   ├── test_runner.py    # [CP5] TestRunnerAdapter + DTO + error
│   ├── git_read.py       # [CP5] GitReadAdapter (read-only) + DTO + error
│   └── secrets.py        # [CP2] SecretProvider Protocol (no SecretError — absence is None)
├── adapters/
│   ├── env_secret_provider.py  # [CP2] EnvSecretProvider (os.environ)
│   ├── litellm_client.py   # [CP3] LiteLLMCompletionClient seam + LiteLLMSdkClient (lazy import)
│   ├── litellm_mapping.py  # [CP3] model id / payload / response+usage+finish normalization
│   ├── litellm_errors.py   # [CP3] map_litellm_error -> taxonomy (lazy import)
│   ├── litellm_cloud.py    # [CP3] LiteLLMCloudAdapter (provider-neutral; OpenAI bootstrap)
│   ├── adapter_log.py      # [CP3] sanitized structured logging (stdlib)
│   ├── ollama_local.py     # [CP4] OllamaAdapter (is_local, api_base)
│   └── factory.py          # [CP6] build_llm_adapter(config, secrets) — provider hợp lệ
├── config/
│   ├── models.py         # [CP2] + ModelsConfig, ModelEndpointConfig
│   ├── timeout.py        # [CP2] validate_timeout / resolve_timeout (float)
│   └── constants.py      # [CP2] + allowed keys, env names, DEFAULT/MAX timeout

tests/
├── contracts/llm_contract.py   # [CP1] reusable LLMAdapterContract (Fake/Cloud/Ollama)
└── support/fake_llm.py         # [CP1] FakeLLMAdapter (test-only)
```

**Hướng phụ thuộc:** `adapters → application/ports` (import port + error). `core` & `application/services` **không** import `adapters`/`litellm`/`openai`. `adapters/testing` (nếu có) và `tests/support` **không** import `litellm`. LiteLLM + OpenAI **bị giam** trong `adapters/litellm_*`, `adapters/ollama_local`.

---

## 5. Usage, error & timeout semantics (chốt cho toàn phase)

**ModelUsage / UsageStatus** (biểu diễn trung thực dữ liệu thiếu):
- `UsageStatus ∈ {MEASURED, ESTIMATED, UNAVAILABLE}`.
- `UNAVAILABLE` ⇒ `tokens_in == tokens_out == tokens_total == None` (KHÔNG fill 0).
- `MEASURED`/`ESTIMATED` ⇒ `tokens_in` và `tokens_out` đều present (dùng `TokenCount`, đã reject âm); nếu `tokens_total` present thì `== tokens_in + tokens_out`.
- **Không** monetary cost ở bất kỳ đâu (energy/cost = Phase 3). `ESTIMATED` chỉ là trạng thái contract; CP1 không implement estimation.

**Error taxonomy** (neutral, kế thừa `AntError`, mỗi loại có `code` ổn định + `retryable`):
| Error | code | retryable mặc định |
|---|---|---|
| `AdapterTimeoutError` | `adapter.timeout` | True |
| `AdapterConnectionError` | `adapter.connection` | True |
| `AdapterRateLimitError` | `adapter.rate_limit` | True |
| `AdapterAuthenticationError` | `adapter.authentication` | False |
| `AdapterInvalidRequestError` | `adapter.invalid_request` | False |
| `AdapterProviderError` | `adapter.provider` | False (phải xác định rõ khi biết nguyên nhân) |
| `AdapterResponseError` | `adapter.response` | False |
- `AdapterAuthenticationError` **không** là subclass/alias của `AdapterInvalidRequestError`.
- Public message/repr: chỉ `code`/`retryable`/sanitized `provider`/`model`; **không** secret, full prompt, full response, raw provider exception.

**Timeout precedence (float):** `request.timeout_seconds > endpoint config > DEFAULT_TIMEOUT_SECONDS` (tất cả `float`); hợp lệ = số hữu hạn, `>0`, `≤ MAX_TIMEOUT_SECONDS`. Reject `bool`/`NaN`/`±inf`/ngoài biên (không clamp/round/ép int). `DEFAULT_TIMEOUT_SECONDS=120.0`, `MAX_TIMEOUT_SECONDS=600.0`.

**Config identifier (`provider`/`model`/`base_url`):** phải là string non-empty, **không** surrounding whitespace (`value != value.strip()` ⇒ reject). Không auto-strip/lowercase/normalize. (Secret thì ngược lại: trả nguyên giá trị, chỉ `""`→`None`.)

---

## 6. Checkpoint plan (6 checkpoint, tuần tự)

| CP | Tên | Phụ thuộc | Real impl? |
|----|-----|-----------|-----------|
| CP1 | LLM async contract, error taxonomy, FakeLLMAdapter, contract test kit | — | Test double |
| CP2 | Model config, timeout policy, SecretProvider | CP1 | — |
| CP3 | LiteLLM shared infra + provider-neutral cloud adapter (OpenAI bootstrap) | CP1,CP2 | **Real** |
| CP4 | Ollama adapter | CP1,CP2,CP3 | **Real** |
| CP5 | Tool contracts + separated fake implementations | CP1 | Fake |
| CP6 | Factory, composition wiring, boundary regression, live verification, closure | CP2–CP5 | wiring |

### CP1 — LLM async contract, error taxonomy, fake adapter, contract test kit
- **Mục tiêu:** public application boundary provider-neutral, async, đủ ổn định để CP3/CP4 implement mà không sửa contract.
- **In scope:** `application/ports/llm.py` (Protocol `async complete` + DTO §4/§5); `application/ports/llm_errors.py` (taxonomy §5); `tests/support/fake_llm.py` (FakeLLMAdapter async, scripted response, ghi nhận request, mô phỏng error + usage measured/unavailable); `tests/contracts/llm_contract.py` (`LLMAdapterContract` tái dùng).
- **Out of scope:** LiteLLM/OpenAI/Ollama invocation; config model/provider; SecretProvider impl; timeout resolution; logging infra; tool contracts; factory; composition; CLI; live; retry; streaming; context package; energy/persist. **Không thêm dependency.**
- **Invariant:** ModelUsage §5; auth ≠ invalid-request; DTO immutable (frozen); response luôn provider+model; mọi AdapterError là AntError; provider-neutral (không assumption OpenAI).
- **Tests (deterministic, no network/secret; `asyncio.run` trong pytest sync):** ModelUsage MEASURED/UNAVAILABLE; token âm reject; in/out/total bất nhất reject; missing token không bị zero-fill; fake async trả response + ghi request; mô phỏng 7 error category; retryable đúng; auth ≠ invalid; error str/repr không lộ secret/prompt được plant; contract suite PASS với Fake; AST application/ports không import adapters/litellm/openai.
- **Acceptance:** xem §9 bảng; **Quality gate 5/5**; 128 test Phase 1 + test CP1 PASS.
- **Closure:** contract+error+fake+kit xanh, gate xanh, scope audit sạch.

### CP2 — Model config, timeout policy, SecretProvider
- `config/models.py` (`ModelEndpointConfig`/`ModelsConfig`; `ResolvedConfig.models` default empty) + `config/constants.py` (allowed keys; `DEFAULT_TIMEOUT_SECONDS=120`/`MAX_TIMEOUT_SECONDS=600`) + `config/timeout.py` (`validate_timeout`/`resolve_timeout`, precedence `request>endpoint>default`, reject ngoài biên không clamp) + `config/resolver.py` (parse/validate `models`); `application/ports/secrets.py` (`SecretProvider.get->str|None`, **không** `SecretError` — absence là `None`); `adapters/env_secret_provider.py` (`EnvSecretProvider`, đọc `os.environ`, infra layer) + `tests/support/fake_secret_provider.py`. Config Phase 1 cũ vẫn load (additive, giữ document version); unknown-key reject; secret không vào config/log/repr. Missing-secret→`AdapterAuthenticationError` để CP3/CP6.
- **Timeout type đã thống nhất (corrective):** toàn bộ timeout (config `ModelEndpointConfig.timeout_seconds`, `resolve_timeout`, constants) là `float`, khớp trực tiếp `LLMRequest.timeout_seconds: float | None`. CP3 dùng output `resolve_timeout` as-is, không cần conversion. Không còn mismatch float/int.

### CP3 — LiteLLM shared infra + provider-neutral cloud adapter (OpenAI bootstrap) — IMPLEMENTED
- **Dependency:** `litellm>=1.89.3,<1.90` (ADR-0003; tested on **1.89.3**, Python 3.11.8). Pulls `openai` transitively (Ant code never imports `openai` directly). LiteLLM pins `typer` 0.25.1 (downgrade từ 0.26.7; gate vẫn PASS).
- **Module layout (deviation từ plan gốc):** thay vì một `litellm_base.py` + package `observability/`, tách theo SRP trong `adapters/`: `litellm_client.py` (seam, **lazy import** litellm), `litellm_mapping.py` (pure mapping, không import litellm — đọc raw duck-typed), `litellm_errors.py` (`map_litellm_error`, lazy import), `litellm_cloud.py` (`LiteLLMCloudAdapter`), `adapter_log.py` (sanitized logging). Không tạo package `observability/` (tránh thêm top-level package ngoài PROJECT_STRUCTURE; cần ADR).
- **Seam DI:** adapter nhận `LiteLLMCompletionClient` injectable → test dùng fake, không monkeypatch global; litellm chỉ import khi gọi SDK/map error thật.
- **Semantics:** model id compose một lần `provider/model`, **cho phép nested namespace** trong model (vd `org/name`, `anthropic/name`), chỉ reject khi model đã bắt đầu bằng **chính** prefix `provider/` (tránh double-prefix); không strip/lowercase/split. Request payload allowlist (`stream=False`, `num_retries=0`, timeout float as-is, api_key explicit, api_base chỉ khi có); usage MEASURED/UNAVAILABLE (partial → UNAVAILABLE, không zero-fill; token bool/âm/non-int/total lệch → `AdapterResponseError`); finish reason unknown → `UNKNOWN`; error map theo class (Timeout trước APIConnectionError); `asyncio.CancelledError` pass-through; missing secret → `AdapterAuthenticationError` không gọi SDK.
- **mypy:** override `litellm`/`litellm.*` = `follow_imports=skip` (untyped boundary; không hạ chuẩn code của ta).
- **Tests:** fake seam (no network/secret); contract suite PASS với `LiteLLMCloudAdapter`; error-map test import litellm để dựng exception; gated `@pytest.mark.live_openai` skip mặc định.
- **Contract refinement (corrective, trước khi đóng Phase 2):** adapter là **endpoint-bound** — `LLMRequest` **chỉ** mang content + inference options (messages/system_prompt/temperature/max_output_tokens/timeout_seconds/metadata), **không** chọn model. Đã **xóa hẳn** field `LLMRequest.model` (không alias/deprecated). **Một source of truth duy nhất cho model/provider = `ModelEndpointConfig`** (adapter binding); `LLMResponse` mang provider/model thực tế đã dùng; `LLMAdapter.identity`/log lấy từ endpoint. Model routing/selection thuộc phase sau. (Note N-CP3-1 đã đóng.)

### CP4 — Ollama adapter
- `adapters/ollama_local.py` (`is_local`, `api_base`, dùng `litellm_base`, không duplicate normalization); ollama-down → `AdapterConnectionError(retryable)`. Contract suite (mock); live `@pytest.mark.live_ollama` skip mặc định.

### CP5 — Tool contracts + separated fakes
- `application/ports/{filesystem,shell,test_runner,git_read}.py` (mỗi loại 1 file, SRP) + fake riêng; Git **read-only** (không write op); **không** real exec/enforcement; ShellResponse có exit_code/stdout/stderr/duration.

### CP6 — Factory, composition, boundary regression, live verification, closure
- `adapters/factory.py` (`build_llm_adapter` chỉ provider hợp lệ; reject `fake`); composition wiring (env SecretProvider + factory, không dead bridge); mở rộng AST boundary; **live verification bắt buộc ≥1 lần** (1 OpenAI + 1 Ollama qua cùng contract, sanitized evidence) trước khi tuyên bố COMPLETE; `PHASE_2_COMPLETION_REPORT.md`.

---

## 7. Test strategy (toàn phase)
- Mock `litellm.acompletion` cho mọi contract test → deterministic, no network/secret.
- Fake/in-memory: FakeLLMAdapter, tool fakes, fake SecretProvider.
- Async test bằng `asyncio.run` (ưu tiên stdlib; chỉ thêm dev `pytest-asyncio`/anyio nếu thật cần, có justification, không thêm runtime dep).
- Contract kit `LLMAdapterContract` dùng chung Fake/Cloud/Ollama.
- Regression: full 128 test Phase 1 mỗi CP.
- Live: tách marker `live`/`live_ollama`, skip mặc định; thực thi thành công ≥1 lần trước closure.
- Invariant bắt buộc: ModelUsage §5; litellm/openai type không rò; Git read-only; secret không log.

## 8. Git & integration
- Branch `phase/2-adapters` từ `develop`@`3222300`. 1 commit/checkpoint; gate 5/5 trước mỗi commit. Closure CP6: gate + full suite + AST + live thành công → completion report → merge develop. Rollback: `git revert <cp>`.

## 9. Acceptance criteria CP1 (đo được)
| # | Criterion | Evidence |
|---|---|---|
| 1 | `LLMAdapter.complete` là async/awaitable; Protocol ở `application/ports` | `llm.py`, contract test |
| 2 | DTO immutable; provider/model luôn có trong response | unit + contract |
| 3 | ModelUsage MEASURED hợp lệ (total=in+out) | unit |
| 4 | ModelUsage UNAVAILABLE hợp lệ; token không bị zero-fill | unit |
| 5 | Token âm reject; in/out/total bất nhất reject | unit |
| 6 | 7 error category tồn tại; code ổn định; retryable đúng | unit |
| 7 | Authentication ≠ InvalidRequest (không subclass/alias) | unit |
| 8 | Error str/repr không lộ secret/prompt được plant | unit + contract |
| 9 | FakeLLMAdapter async trả response + ghi nhận request; mô phỏng 7 error + usage | contract |
| 10 | Contract suite PASS với FakeLLMAdapter | `test_fake_llm_contract.py` |
| 11 | AST: `application/ports` không import adapters/litellm/openai | `test_import_boundary.py` |
| 12 | Fake/contract kit ngoài `src/`; production không import fake | review + AST |
| 13 | Gate 5/5 PASS; 128 Phase 1 + CP1 test PASS; không file >350 | gate |

## 10. Điểm dừng
Sau CP1: không bắt đầu CP2; không cài LiteLLM; không implement SecretProvider/OpenAI/Ollama; không commit ngoài CP1; dừng để PO review.
