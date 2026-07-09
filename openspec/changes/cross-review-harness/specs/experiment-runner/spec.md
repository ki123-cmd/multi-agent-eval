# experiment-runner

多臂实验编排、重复采样与指标落盘。

## ADDED Requirements

### Requirement: 臂的定义可枚举且正交
实验 MUST 显式区分「实现者模型」「评审者模型」「上下文条件」三个维度。

#### Scenario: 分离模型多样性与上下文隔离
- **WHEN** 运行完整消融
- **THEN** MUST 至少包含：跨模型隔离、同模型隔离、同模型共享上下文
- **AND** MUST 包含镜像方向的臂（Codex 实现 → Codex 隔离评审），以区分「模型多样性」与「某模型本就更擅长评审」

### Requirement: 重复采样
两个 CLI 均不暴露 `temperature` / `seed`，故 MUST 以重复采样估计方差。

#### Scenario: 单 item 多次运行
- **WHEN** 对某 item 运行某臂
- **THEN** MUST 重复 N 次（N 可配，默认 8）
- **AND** 报告 MUST 给出中位数与分布，而非单次点估计

### Requirement: 裁判独立性
裁判模型 MUST NOT 是被比较的任一方。

#### Scenario: 语义匹配 finding 与 golden comment
- **WHEN** 判定某条 finding 是否命中某条 golden comment
- **THEN** MUST 使用第三方模型，并 MUST 对 10–20% 样本做人工抽检
- **AND** MUST 报告裁判与人工的一致性（Cohen's κ）

### Requirement: 截断与降级必须显式记录
系统 MUST NOT 静默降级。

#### Scenario: 评审者不可用
- **WHEN** 某后端 CLI 缺失或调用失败
- **THEN** harness MUST 硬失败退出，MUST NOT 回退为另一个模型冒充该臂
