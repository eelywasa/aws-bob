# Brainy Bob – Phased Development Backlog

## Overview
This backlog outlines a phased roadmap for improving the Brainy Bob Alexa skill (aws-bob). The goal is to evolve the current MVP into a fast, reliable, and delightful household conversational assistant suitable for both adults and children.

Phases are ordered by **user impact first**, then **capability expansion**, then **developer maintainability**.

---

# Phase 1 — Performance, Responsiveness, and Reliability
Goal: Make Brainy Bob feel fast and dependable in everyday use.

## 1.1 Progressive Responses ✅ DONE
User Story:
As a user, when I ask a question, Alexa should immediately respond with a short acknowledgement so it does not feel like the system is frozen.

Tasks:
- Implement progressive response for long-running AI calls
- Trigger progressive response when OpenAI call begins
- Use phrases such as:
  - "Let me think about that…"
  - "One moment…"

Acceptance Criteria:
- Alexa speaks within ~300ms of request
- Long AI responses no longer feel delayed

---

## 1.2 Latency Instrumentation ✅ DONE
User Story:
As a developer, I want to understand where time is spent in the request pipeline.

Tasks:
- Add structured timing logs
- Track:
  - total request time
  - OpenAI API latency
  - DynamoDB latency
  - web search latency

Acceptance Criteria:
- CloudWatch logs show timing breakdown

---

## 1.3 Lambda Cold Start Optimisation ✅ DONE (partial — memory increased to 1024MB)
User Story:
As a user, the first question after inactivity should still feel reasonably fast.

Tasks:
- Increase Lambda memory (512–1024MB)
- Measure cold vs warm response times
- Optional: lightweight scheduled warming

Acceptance Criteria:
- Cold start < 2.5s typical

---

## 1.4 Fail-Fast Timeout Strategy
User Story:
As a user, if something goes wrong, Alexa should quickly apologise rather than waiting silently.

Tasks:
- Add shorter AI timeout
- Provide friendly fallback responses

Acceptance Criteria:
- No long silent delays

---

# Phase 2 — Personalisation and Profiles
Goal: Make Brainy Bob feel aware of household members.

## 2.1 Alexa Voice Profile Integration
User Story:
As a user, Brainy Bob should adapt depending on who is speaking.

Tasks:
- Detect Alexa `personId`
- Map `personId` to user profile
- Persist mapping in DynamoDB

Acceptance Criteria:
- Bob recognises individual speakers

---

## 2.2 Audience Modes
User Story:
As a child, Brainy Bob should explain things simply.

Modes:
- child
- general
- educational

Tasks:
- Extend system prompts
- Allow voice commands:
  - "switch to kid mode"
  - "switch to normal mode"

Acceptance Criteria:
- Different answer styles per mode

---

## 2.3 Per-Person Memory
User Story:
As a family member, my conversations should not interfere with other users.

Tasks:
- Partition memory by personId
- Maintain separate conversation histories

Acceptance Criteria:
- Each household member has independent context

---

# Phase 3 — Search and Grounded Knowledge
Goal: Improve accuracy for real-world questions.

## 3.1 Smart Search Triggering
User Story:
As a user, when I ask about current events, Bob should check the internet.

Tasks:
- Add routing logic for queries requiring fresh data

Examples:
- news
- weather
- sports scores
- opening hours

Acceptance Criteria:
- Search only triggered when useful

---

## 3.2 Voice-Friendly Source Attribution
User Story:
As a user, I should know when Bob is using external information.

Tasks:
- Add short source references

Example:
"According to the BBC…"

Acceptance Criteria:
- Spoken answers remain concise

---

## 3.3 Search Result Caching
User Story:
As a developer, repeated queries should not repeatedly call external services.

Tasks:
- Cache recent search results
- TTL ~5–15 minutes

Acceptance Criteria:
- Reduced external API usage

---

# Phase 4 — Memory Improvements
Goal: Move from raw conversation history to useful long-term memory.

## 4.1 Conversation Summarisation
User Story:
As a system, Bob should summarise old conversations rather than storing raw transcripts.

Tasks:
- Periodically summarise conversation history
- Store summary memory

Acceptance Criteria:
- Context remains useful but compact

---

## 4.2 Memory Types
Add memory classes:

- conversational context
- user preferences
- family facts

Example:
"Sophie likes dinosaurs"

Acceptance Criteria:
- Memories can be referenced later

---

## 4.3 Memory Controls
User Story:
As a user, I should control what Bob remembers.

Voice commands:
- "what do you remember about me"
- "forget that"

Acceptance Criteria:
- Users can inspect and delete memory

---

# Phase 5 — Child Safety and Kid Experience
Goal: Ensure Brainy Bob is safe and fun for children.

## 5.1 Child Safety Policies
Tasks:
- Add stricter filtering for child mode
- Avoid scary or mature content

Acceptance Criteria:
- Safe answers for children

---

## 5.2 Educational Interaction Style
Tasks:
- Encourage curiosity
- Ask follow-up questions

Example:
"Do you know what dinosaur had the longest neck?"

Acceptance Criteria:
- More engaging responses

---

## 5.3 Story Mode
User Story:
As a child, I want Brainy Bob to tell stories.

Tasks:
- Add story mode prompt

Acceptance Criteria:
- Imaginative but calm stories

---

# Phase 6 — Developer Experience
Goal: Make the codebase easier to extend.

## 6.1 Modular Intent Structure
Refactor handler into modules:

- intents/chat.py
- intents/mode.py
- intents/utilities.py

Acceptance Criteria:
- Smaller files

---

## 6.2 Improved Test Coverage
Tasks:
- Add request envelope tests
- Add prompt behaviour tests

Acceptance Criteria:
- Core behaviour validated

---

## 6.3 Local Event Replay Harness
Tasks:
- Save real Alexa requests
- Replay locally

Acceptance Criteria:
- Faster debugging

---

# Phase 7 — Household Superpowers
Goal: Make Brainy Bob uniquely useful at home.

Ideas:

## 7.1 Quiz Mode
Kid-friendly trivia game

## 7.2 Family Planning Helper
Help with:
- meal ideas
- weekend plans

## 7.3 Recipe Assistant
Voice-driven cooking helper

## 7.4 Conversation Companion
Bob can ask questions such as:
"What was the best thing that happened today?"

---

# Suggested Priority Order
1. Progressive responses
2. Latency instrumentation
3. Voice profile detection
4. Audience modes
5. Memory summarisation
6. Handler modularisation
7. Story mode

---

---

# Phase 8 — Slack Companion Interface
Goal: Extend Brainy Bob beyond Alexa with a Slack-based companion interface for asynchronous conversation, collaboration, and artifact sharing.

## 8.1 "Send to Slack" Companion Output (MVP)
User Story:
As a user, when Brainy Bob gives a useful answer on Alexa, I want to send it to Slack so the family can read or continue the conversation later.

Tasks:
- Create Slack incoming webhook
- Store webhook URL securely (AWS Secrets Manager)
- Add Alexa command patterns such as:
  - "Send that to Slack"
  - "Post that to family Slack"
  - "Send this story to Slack"
- Format message for Slack (plain text or Slack blocks)

Acceptance Criteria:
- Bob can post responses to a configured Slack channel
- Messages include useful formatting and context

---

## 8.2 Slack Slash Command Interface
User Story:
As a Slack user, I want to ask Brainy Bob questions directly from Slack.

Tasks:
- Create Slack app
- Implement `/bob` slash command
- Route command requests to Brainy Bob Lambda endpoint

Examples:
- `/bob dinner ideas with pasta and tomatoes`
- `/bob summarise this conversation`

Acceptance Criteria:
- Bob responds directly in Slack thread

---

## 8.3 Slack Direct Message Bot
User Story:
As a user, I want to have a longer text conversation with Brainy Bob in Slack.

Tasks:
- Enable Slack Events API
- Allow DM conversations
- Reuse Brainy Bob conversation engine

Acceptance Criteria:
- Slack conversations maintain context

---

## 8.4 Cross-Channel Continuity
User Story:
As a user, I want to continue a conversation started on Alexa in Slack.

Tasks:
- Share conversation context across channels
- Tag memory with channel metadata

Acceptance Criteria:
- Alexa conversations can be resumed in Slack

---

## 8.5 Slack Artifact Types
Examples of structured outputs Bob can send:

- recipes
- weekly plans
- quiz questions
- story transcripts

Acceptance Criteria:
- Messages formatted with Slack Block Kit

---

## 8.6 Family Collaboration Mode
User Story:
As a family, we want to collaborate with Brainy Bob in a shared Slack channel.

Tasks:
- Create shared "family" channel support
- Enable threaded responses

Acceptance Criteria:
- Bob participates in channel discussions

---

# Suggested Priority Order
1. Progressive responses
2. Latency instrumentation
3. Voice profile detection
4. Audience modes
5. Memory summarisation
6. Handler modularisation
7. Story mode
8. Slack companion output

---

End of backlog

