# reviewer-adapter

以对称参数驱动 Claude / Codex 评审者。对称性是实验有效性的前提——两侧的能力面、输入、rubric 必须一致，否则「跨模型差异」会与「配置差异」混淆。

## ADDED Requirements

### Requirement: 能力面对称
两侧评审者 MUST 均无工具调用能力。

#### Scenario: 驱动 Codex 评审者
- **WHEN** 以 codex 后端运行评审
- **THEN** MUST 使用 `--sandbox read-only --ephemeral --skip-git-repo-check`
- **AND** MUST 通过 `--output-schema` 强制结构化输出，通过 `-o` 提取结果

#### Scenario: 驱动 Claude 评审者
- **WHEN** 以 claude 后端运行评审
- **THEN** MUST 通过 `--disallowedTools` 关闭全部工具，并设 `--max-turns 1`
- **AND** MUST 使用 `--output-format json` 提取结果与用量

### Requirement: 记录真实调用参数
每条结果 MUST 记录实际使用的模型 slug、推理档位与完整命令行。

#### Scenario: 结果落盘
- **WHEN** 一次评审完成
- **THEN** 结果 MUST 含 `model`、`effort`、`argv`、`tokens`、`cost_usd`、`duration_ms`

### Requirement: 结构化输出能力的不对称必须被记录
Codex 支持 `--output-schema` 而 `claude -p` 不支持，系统 MUST 显式记录并报告该不对称。

#### Scenario: Claude 侧输出不合 schema
- **WHEN** Claude 返回的文本无法解析为合法 verdict
- **THEN** 系统 MUST 记为 `INVALID` 并计入 `schema_failure_rate`
- **AND** 该指标 MUST 在报告中与 Codex 侧并列呈现
