# 贡献评估模型 · 便携参考卡

粘贴此文件给任意 LLM，即可接手项目迭代。

## 项目身份

用 12 维度尺子衡量任何一件事的贡献。1 贡献点 ≡ 1 有效工作小时。

**三层软件架构**（模块解耦）：
- 模块1 事件定义：人+行为+耗时 → 结构化事件
- 模块2 12维度尺子：事件描述 → 维度得分+相关性+确定性
- 模块3 计算工具：得分+相关性+时间 → 有效贡献小时+排名。内部因果三层 L1(事件本身)→L2(直接影响)→L3(涟漪扩散)

> **关键**：模块1/2/3 ≠ L1/L2/L3。前者是软件解耦，后者是模块3内部的因果模型。

## 数据架构

```
data/{person_id}/
  pending.json   ← 待分配池（父事件不明确的行为暂存于此）
  ledger.json    ← 个人账本（已分配行为 + 事件 + 结算状态）
```

**代码关系**：model.json → evaluator.py（计算，纯函数）← ledger.py（数据管理，调用 evaluator 做结算）

## API 速查

| 函数 | 用途 |
|------|------|
| `add_event(person_id, name, parent_event_id?)` | 创建事件，返回 eid |
| `complete_event(person_id, event_id, outcome)` | 完结事件，返回未结算分配列表 |
| `get_ongoing_events(person_id)` | 进行中的事件（冷启动用）|
| `get_pending_pool(person_id)` | 待分配池列表（冷启动用）|
| `add_pending(person_id, description, hours, dimensions, asset?, notes?)` | 写入待分配池 |
| `classify_pending(person_id, pending_id, parent_event_id)` | 从待分配池移入账本 |
| `add_behavior(person_id, description, hours, dimensions, parent_event_id?, asset?)` | 记录行为（无 parent_event_id → 等同 add_pending）|
| `allocate(person_id, behavior_id, parent_event_id)` | 追加分配（资产复用）|
| `settle(person_id, behavior_id, allocation_index, scores, certainty?)` | 写入/修正评分 |
| `get_unsettled_allocations(person_id, event_id)` | 某事件未锁定分配（完结时回溯用）|
| `get_event_behaviors(person_id, event_id)` | 某事件全部已分配行为 |
| `compute_contribution(person_id, behavior_id, allocation_index, model?)` | 单次有效小时 + 排名 |
| `compute_event_total(person_id, event_id, model?)` | 事件累计有效小时（跨会话）|
| `compute_person_total(person_id, model?)` | 个人累计总分 + 排名 |

## 12 维度尺子

| 维度 | 权重 | 正向 | 负向 |
|------|------|------|------|
| 创意 | 1.2 | 新方案、新视角、新思路 | 抄袭、扼杀创意、思维僵化 |
| 规划 | 1.0 | 拆解任务、制定可行路径 | 计划混乱、方向错误 |
| 决策 | 1.3 | 做出正确判断和选择 | 优柔寡断、错误判断 |
| 行动 | 1.5 | 落地执行、产出结果 | 拖延、半途而废 |
| 技能 | 1.0 | 运用专业能力完成工作 | 能力不足、粗制滥造 |
| 协作 | 1.1 | 沟通配合、帮助他人 | 冲突、信息封闭 |
| 领导 | 1.2 | 组织激励、引导方向 | 独断、打压 |
| 学习 | 0.8 | 获取新知、提升能力 | 拒绝学习、固步自封 |
| 维护 | 0.9 | 修复问题、保持稳定 | 制造隐患、留下烂摊子 |
| 影响力 | 1.4 | 正面效应扩散 | 负面传播、损害声誉 |
| 创新 | 1.3 | 新方法解决老问题 | 为创新而创新、破坏有效系统 |
| 复利 | 1.5 | 持续复利回报（工具/知识/体系积累）| 一次性消耗、透支未来 |

## 评分协议

### 四层判断（逐层，每个维度）

```
L1 相关性：跳过（不相关）→ 不进L1不进L2 | 相关 → 进L1权重和，进入L2
L2 效果方向：+1~+5(正向因果) | -5~-1(负向因果，父事件完结前不存在) | 0(零效果) | 不可评(父事件未完结/未分配)
L3 零效果类型：潜伏价值(当前没用，未来可能有用) | 纯浪费(确实没用)
L4 确定性：确定 → score×1.0 | 模糊 → score×0.5
```

**核心**：判断的是行为对父事件最终结果的**因果贡献**，不是行为本身好坏。执行质量≠因果贡献。评分可修正。

### 三种结算模式

| 模式 | 条件 | 行为完成时 | 父事件完结时 |
|------|------|-----------|-------------|
| 即时结算 | 叶子事件（结果立即可见）| 评分锁定 | — |
| 暂定结算 | 子事件（父事件进行中）| 暂定评分 | 回溯修正→锁定 |
| 延期结算 | 父事件不明确 | 只记录不评分 | 归类→暂定→锁定 |

## 分类协议

### 冷启动（新对话首次执行）
1. `get_ongoing_events(person_id)` → 2. `get_pending_pool(person_id)` → 3. 有上下文则结合判断

### 父事件判断（三条规则，命中即停）

```
规则1 叶子事件？→ 父事件=自身（新建同名事件），即时结算
规则2 用户明确说了/上下文可推断？→ 使用已有事件ID
规则3 以上都不满足？→ add_pending() 写入待分配池
```

### 待分配池归类（四条途径）
- A: 用户后续说明用途 → `classify_pending()`
- B: 资产被某事件消耗 → 自然流向使用处
- C: 长期未消耗 → 留在 pending；确定永不被消耗 → 纯浪费
- D: 多事件消耗同一资产 → `allocate()` 多次分配（复利维度）

### 完结判断
- 叶子事件：行为完成
- 子事件：所有子行为完成 + 产出可验证
- 父事件：所有子任务完成 + 目标达成或终止 → `complete_event()`

## 计算公式

```
有效贡献小时 = A × (L1 / total_weight) × l2_factor × l3_factor

L1 = Σ(相关维度权重) × 小时          ← 事件本身价值池
l_factor = 1 + L2(或L3) / (对应权重和 × quality_scale)
```

| 参数 | 值 | 说明 |
|------|-----|------|
| A | 1.0 | 总体校准 |
| quality_scale | 2.5 | 均分+2.5→系数2，均分0→系数1，均分-2.5→系数0，均分-5→系数-1 |
| fuzzy_factor | 0.5 | 模糊维度折扣 |
| total_weight | 14.2 | 全部12维度权重和 |

## 排名映射

| 名称 | 累计有效小时 |
|------|-------------|
| 破坏者 | < 0 |
| 新手 | 0 ~ 8 |
| 实践者 | 8 ~ 40 |
| 贡献者 | 40 ~ 200 |
| 创造者 | 200 ~ 1000 |
| 引领者 | 1000+ |

## 端到端流程

```
0. 冷启动：get_ongoing_events + get_pending_pool
1. 用户描述行为（做了什么、多久、属于哪件事）
2. 分类协议判断父事件：规则1(叶子)→新建事件 | 规则2(明确)→用已有ID | 规则3(不明确)→add_pending→结束
3. (待分配池 review → classify_pending)
4. add_behavior() 写入账本
5. 按四层判断给每个相关维度打分
6. settle() 写入评分（父事件ongoing→provisional, completed→settled）
7. 父事件完结 → complete_event() → 回查未锁定评分 → 重新 settle()
8. compute_contribution() → 单次有效贡献小时 + 排名
9. compute_event_total() → 事件累计（跨会话）
10. compute_person_total() → 个人累计总分 + 排名
```
