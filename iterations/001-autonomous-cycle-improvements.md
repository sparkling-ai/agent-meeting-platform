# Iteration 001 — Autonomous Cycle Improvements

**Date:** 2026-05-30
**Source:** V1/V2/V3 retrospective + Dandan's direct inputs
**Status:** 📋 Input for next planning meeting

---

## Problems Discovered (from 3 autonomous cycles)

### 🔴 Critical: Team Loops Instead of Deciding
**Observed in:** V1 (all 9 meetings), partially fixed in V2/V3
- Team members repeat the same concerns ("scalability", "technical debt") without converging
- Round 3 often still produces risks/objections instead of proposals
- Even with CEO override logic, the underlying LLM prompt needs to push harder for concrete output
- **Impact:** Meetings feel productive but produce no actionable decisions

### 🔴 Critical: Dev Phase Only Ran 1 of 3 Cycles
**Observed in:** V3
- Claude Code took 3-5 min per task, serial execution
- Only cycle 1 tasks got real code; cycles 2-3 timed out
- **Impact:** Two-thirds of sprint tasks were never implemented

### 🟡 Moderate: Task Quality — Abstract vs Concrete
**Observed in:** V1, V2, V3
- LLM generates tasks like "Evaluate Scalability" (V1) instead of "Fix DB auth in test config"
- Tasks don't reference actual files, paths, or line numbers in the codebase
- **Impact:** Claude Code works on generic features instead of high-impact fixes

### 🟡 Moderate: Meeting Repetition Across Cycles
**Observed in:** V2, V3
- Cycle 2/3 planning meetings don't effectively build on cycle 1's outcomes
- Same themes recur (scalability, UX, tech debt) without progress
- **Impact:** Diminishing returns per cycle

### 🟢 Minor: Claude Code `--prompt` Bug
**Status:** ✅ Fixed in V2
- Used `--prompt` flag instead of positional argument
- Fixed to `claude --print <prompt>`

### 🟢 Minor: Python Output Buffering
**Status:** ✅ Fixed in V3
- `tee` showed nothing because Python buffers stdout
- Fixed with `PYTHONUNBUFFERED=1` and `flush=True`

---

## Dandan's Inputs for Next Meeting

### 1. 🗳️ Voting vs Moderator Authority Balance
**Question:** Vote is not always the most accurate way of making decisions. How to balance the moderator's say vs team voting?

**Context:**
- Current system uses simple majority vote (>50% yes to pass)
- Moderator has intervention power but final decisions go to vote
- In reality, voting can lead to groupthink or average decisions instead of optimal ones
- The CEO/moderator should sometimes overrule when they see a clearer path

**Possible approaches to discuss:**
- Moderator veto power (can overrule a vote with justification)
- Weighted voting (moderator vote counts more)
- Decision categories: some need votes, some are moderator calls
- "Disagree and commit" — moderator decides, team commits

### 2. 💰 Rethinking "Cost" in the AI Age
**Key insight:** Function/code change cost has dropped dramatically with agentic coding.

**Sub-points:**

**a) Dev cost is much lower now:**
- Functions get developed much faster than with traditional human developers
- This changes the cost-benefit analysis — building more is cheaper
- BUT: overdo or overcomplicated functions hurt user experience
- **Need balance:** Build fast, but keep it simple for users

**b) User experience is paramount for human users:**
- Must be intuitive and easy to start
- Even if dev cost is cheap, complex features = confused users
- Simplicity > feature count
- "5-minute quickstart" should be a hard metric

**c) User acquisition cost is still high (but changing):**
- Marketing, finding users, distribution — still costly
- But AI age may change how users discover and adopt products
- Need research: How do users find and evaluate AI tools in 2026?
- What are the new distribution channels? (AI directories, word-of-mouth in AI communities, etc.)

### 3. 🔍 Research Needed
- How are AI tools discovered and adopted by users in 2026?
- What distribution channels work for AI developer tools?
- What makes an AI tool "go viral" vs fade out?
- Competitor analysis: how do similar meeting/collaboration AI tools acquire users?

---

## Expected Outcomes from Next Meeting

1. **Decision framework:** Clear rules on when moderator decides vs when to vote
2. **Cost-aware development principles:** Updated guidelines balancing fast dev with user simplicity
3. **User acquisition research plan:** Concrete tasks for researching AI-era distribution
4. **Process improvements:** How to prevent looping and ensure task quality
5. **Parallel dev execution:** Run Claude Code tasks in parallel, not serial

---

## Metrics to Track

| Metric | V1 | V2 | V3 | Next |
|--------|----|----|-----|------|
| Proposals per meeting | 0 | 3-5 | 3-5 | ? |
| Real code commits | 0 | 0 | 5 | ? |
| Cycles with real dev | 0/3 | 0/3 | 1/3 | 3/3 |
| Task concreteness | Low | Medium | Medium | High |
| Meeting loop score | High | Medium | Low | ? |
