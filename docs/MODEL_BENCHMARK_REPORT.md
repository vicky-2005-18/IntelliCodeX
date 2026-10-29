# IntelliCodeX — Multi-Model Empirical Benchmark Report

> **Generated**: 2026-10-29 13:36:08
> **Benchmark Target**: Empirical comparison across local coding models under realistic hardware constraints (RTX 3050 4GB VRAM / Local Ollama).

---

## 1. Executive Summary & Model Leaderboard

| Rank | Model | Parameters | Bug F1 | Repair Pass Rate | Q&A Grounding | Generation Speed | Avg Latency | Overall Score |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 🥇 **#1** | `qwen2.5-coder:7b` | 7B Parameter Tier | 100.00% | 100.00% | 100.00% | 8.9 tok/s | 8.36s | **100.00 / 100** |
| 🥈 **#2** | `deepseek-coder:6.7b` | 7B Parameter Tier | 100.00% | 100.00% | 100.00% | 8.1 tok/s | 12.61s | **100.00 / 100** |
| 🥉 **#3** | `qwen2.5-coder:3b` | 3B Parameter Tier | 100.00% | 100.00% | 100.00% | 75.0 tok/s | 5.56s | **100.00 / 100** |
| **#4** | `codellama:7b` | 7B Parameter Tier | 80.00% | 100.00% | 100.00% | 7.0 tok/s | 12.37s | **93.00 / 100** |
| **#5** | `starcoder2:3b` | 3B Parameter Tier | 0.00% | 50.00% | 100.00% | 84.1 tok/s | 5.51s | **42.50 / 100** |

---

## 2. Track 1: Bug Detection & Diagnostic Review

Measures model sensitivity to intentional planted defects (syntax errors, undefined variables, off-by-one, type errors, zero divisions) versus clean control functions.

| Model | TP | FP (False Alarms) | FN (Missed) | TN | Precision | Recall | F1 Score | Detection Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `qwen2.5-coder:7b` | 4 | 0 | 0 | 3 | 100.00% | 100.00% | **100.00%** | 8.36s |
| `deepseek-coder:6.7b` | 4 | 0 | 0 | 3 | 100.00% | 100.00% | **100.00%** | 12.61s |
| `qwen2.5-coder:3b` | 4 | 0 | 0 | 3 | 100.00% | 100.00% | **100.00%** | 5.56s |
| `codellama:7b` | 4 | 2 | 0 | 1 | 66.67% | 100.00% | **80.00%** | 12.37s |
| `starcoder2:3b` | 0 | 0 | 4 | 3 | 0.00% | 0.00% | **0.00%** | 5.51s |

---

## 3. Track 2: Automated Code Repair & Patch Generation

Evaluates patch synthesis directly against unit test suites in temporary isolated environments (KeyError, ZeroDivision, TypeError, IndexError).

| Model | Cases Evaluated | Valid AST Syntax | Single-Shot Pass Rate | Closed-Loop Pass Rate | Tests Passed | Repair Latency |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `qwen2.5-coder:7b` | 2 | 100.00% | 50.00% | **100.00%** | 2 / 2 | 19.71s |
| `deepseek-coder:6.7b` | 2 | 100.00% | 50.00% | **100.00%** | 2 / 2 | 39.19s |
| `qwen2.5-coder:3b` | 2 | 100.00% | 0.00% | **100.00%** | 2 / 2 | 7.16s |
| `codellama:7b` | 2 | 100.00% | 100.00% | **100.00%** | 2 / 2 | 23.86s |
| `starcoder2:3b` | 2 | 100.00% | 50.00% | **50.00%** | 1 / 2 | 6.21s |

---

## 4. Track 3: Codebase Q&A & Technical Grounding

Evaluates multi-file context understanding and architectural comprehension (Flask routing, request contexts, cookies, error handling).

| Model | Total Qs | Grounded Citations | Grounding Rate | Generation Speed | Output Tokens |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `qwen2.5-coder:7b` | 2 | 2 | **100.00%** | 8.9 tok/s | 760.5 |
| `deepseek-coder:6.7b` | 2 | 2 | **100.00%** | 8.1 tok/s | 533.5 |
| `qwen2.5-coder:3b` | 2 | 2 | **100.00%** | 75.0 tok/s | 482.0 |
| `codellama:7b` | 2 | 2 | **100.00%** | 7.0 tok/s | 535.5 |
| `starcoder2:3b` | 2 | 2 | **100.00%** | 84.1 tok/s | 595.5 |

---

## 5. Architectural Recommendations & VRAM Offloading Analysis

1. **3B Parameter Class (`qwen2.5-coder:3b`, `starcoder2:3b`)**:
   - **VRAM Footprint**: ~1.8 - 2.0 GB. Fully loads into 4GB VRAM without CPU spillover.
   - **Inference Speed**: High throughput (~30-50 tokens/s on RTX 3050).
   - **Recommended Role**: Ideal for interactive real-time typing completion, TUI navigation, and lightweight syntax repairs.

2. **7B Parameter Class (`qwen2.5-coder:7b`, `codellama:7b`, `deepseek-coder:6.7b`)**:
   - **VRAM Footprint**: ~4.2 - 4.8 GB. Incurs partial CPU offloading on 4GB VRAM hardware.
   - **Inference Speed**: Lower throughput (~8-15 tokens/s on 4GB VRAM laptop setups).
   - **Code Quality**: Superior logical reasoning on multi-variable bug repairs, error traces, and architectural synthesis.
   - **Recommended Role**: Best for comprehensive offline code reviews, closed-loop regression repairs, and multi-file RAG answers.

3. **Optimal Dual-Engine Strategy for IntelliCodeX**:
   - Use `qwen2.5-coder:3b` for fast inline TUI completions and live interactive chat.
   - Route deep patch synthesis (`/repair`) and multi-repo audits (`/review`) to `qwen2.5-coder:7b`.
