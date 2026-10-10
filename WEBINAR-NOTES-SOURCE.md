**AAW Webinar 01 — Build and Launch an AI Agent**

Build AI Agent to solve one of SMEs in Egypt.

Criteria for building the Agent in hackathon:

- Agents work "Does it work?"
- Correct results
- Consume the least number of tokens
- Effective
- Self improving "Added value when any problem happens like there is missing data or the message sent from the user is unclear"
- ROI "Agents Vs Hعman Cost"
- Save cost to the company
- Save time to company
- Revenue generated

Humans decide what & why. Agents execute how.

The job becomes directing the work; not doing all of it.

Startups now in USA for example build apps to help AI Agents. As nowadays when I build an AI Agent and tries to integrate it with a software designed for human they see there are barriers that human user experience is different than the AI Agent experience for example Agent didn't need to see images it needs specific type of data.

In Browsers for example AI Agent takes screenshots for the browser and convert these screenshots to text then take these text and from it know what it needs to make then know where it needs to click and the next action. So, this process has high cost to the model and has a lot of hassles.

Humans put strategy responsible for creativity, judgement, and relationships; while Agents responsible for execution like research, content, code, ops. Together we are planning, besides break goals into tasks.

**From manual tools to agent teams:**

\- Before: Manager -> employees -> software programs "e.g. CRM" (people manually operate every tool)

\- Now: Manager -> employees -> AI Tools/ AI Agents -> software programs (people use AI tools but context stays scattered)

\- After: Manager -> Harness Layer -> software tools (Agents use the tools while reusable company context builds) "context layer - structure docs, learns from use, A2A"

**What is an AI Agent?**

Chatbot ansers questions while agent does work.

**What is an agent made of?**

1. LLM "Brain"
2. Harness "Operating System/ Instructions"
3. Tools "Hands/ Integrations"
4. Context "what it knows now/ Personalization"
5. Memory "what it remembers"

Intelligence is not enough - the system around the model makes it useful.

There is a difference between software and model for example ChatGPT and GPT5.5, GPT ASTRA besides other models

The cost of using model like GPT in your app using APIs introduced from OpenAI platform is much more using it in chatGPT for example you can send 1000 messages in chatGPT by pro subscription 20Dollars/month while integration with API cost is higher as there is cost for the message you sent and the response of the model.

Because of this chatGPT and Claude are the top in the market as they have advantage in the price according to the other competitors.

ChatGPT, Claude, Gemini all of these are generic AI Agents that are not built to fulfil a specific case.

For example if I need to make a marketing campaign. I can use chatGPT but I need to have experience in marketing and know how to make marketing campaign to begin telling chatGPT what exactly to do. The gap exist when I as a business owner don't have any background in Marketing, so I can't just send to chatGPT what I want.

In Agent case it is different. You as an AI Agent builder you can setup harness to ask user for example at first what his career or domain for example you see harness of the user answer is restaurant you ask him of restaurant location and reviews.

N8n is not the ideal AI Agent.

The main task in the hackathon is to build this harness.

Now I give agent instructions then give it the tools to be able to work. Without tools it says, with tools it does.

chatBot vs workflow vs AI Agent "ideal"

AI Agent can improves itself by reviewing its results and responses during the time and begin to recommend enhancements, and the user whether accepts or not.

Also, it can self improve itself if it makes anything wrong like returning missing data it learns from this err and don't repeat it.

It can do this form its memory.

Better context -> better work

Pro active agent

Personal Agent

Coding Agents

Design Agents

Voice Agents

**Different ways to build AI Agents**

1. Claude/ ChatGPT cowork "simple AI workflows"
   1. Can't do: self-improvement - overcome errors - build a context layer - deep tool integeration - multi-model
2. AI automation platforms "advanced AI workflows"
   1. Examples: n8n.io - make
   2. Can't do: self-improvement - overcome errors - build a context layer
3. Agent Builders "no-code agents"
   1. Visula, no-code platforms for creating agents with prompts, workflows, tools, and integerations - no engineering required.
   2. Example: Hyperagent - Relevance AI - AGENTX - Wesam.ai
   3. Best for: beginners - bussiness users - rapdi prototypes - simple agent workflows
   4. Can't do: self-improvement, overcome errors, build a context layer
4. Open-source agent platforms "OpenClaw - Hermes"
5. Agentic frameworks "full control, in code"
   1. Examples: crewai - mastra

**Agents vs Human Cost**

Himan -> Hours

Agents -> Token

**Steps to follow at first:**

1. Define small business I need
2. Define the jobs in this business
3. Jobs that businesses can not afford like someone do interview, someone makes sales outreach

The new era will be AI Agent prompting humans

The difference between junior and Senior that Junior asks what you need while senior iform of the steps he will do and asks for any comment. Think about this

**Search More:**

- MCP
- GrokBot
- Login with chatGPT

**Resources:**

- Composio
- Airbyte

**AAW Webinar 02 — From Generative AI to Autonomous Systems**

An **autonomous system** is a system capable of achieving a specific goal or performing complex tasks **without continuous human intervention**.

Hardcore AI

Overfitting

Solution Architect

The model is not the system. We start sitting a goal and model go through this loop:

Decide -> Use Tool -> Observe "state variables" -> Validate -> Continue/ Stop

### 🔄 Generative AI vs. Autonomous Systems

Your webinar outlines the transition between these two paradigms:

- **Generative AI (The "Chat" Era):** You give a prompt ("Write me an itinerary for Dubai"). The AI generates text. It is a single-turn interaction. It doesn't do anything in the real world. It just talks.
- **Autonomous Systems (The "Agentic" Era):** You give a goal ("Plan a 4-day trip under \$2,000 and book it"). The AI breaks this down into steps, searches the web, calculates costs, fills out forms, and executes the booking. It does things.

### ⚙️ Key Characteristics of an Autonomous System

Based on your first prompt's loop (Decide -> Use Tool -> Observe -> Validate -> Continue/Stop), an autonomous system has:

1. **Goal Orientation:** It is given a goal (e.g., "Plan a trip under \$2,000") rather than a rigid list of exact steps.
2. **Environment Awareness (Observe State Variables):** It can "read" the world around it—pulling live flight prices, checking hotel availability, or reading traffic maps.
3. **Tool Use:** It can execute actions (Deterministic tools like a calculator, or Indeterministic tools like a web search API or a booking API).
4. **Decision-Making & Planning:** It decides which tools to use and when. It can break a big goal into smaller sub-tasks.
5. **Self-Correction (Failure Recovery):** If a hotel is sold out, it doesn't crash. It reads the error, adjusts its plan, and tries a different hotel.
6. **The "Autonomy Dial":** As your screenshot noted, autonomy isn't a binary on/off switch. It's a dial.
   - Low Autonomy: The AI researches hotels, but pauses and asks the human to click "Book."
   - High Autonomy: The AI books the hotel, Ubers, and activities without asking.
   - Your travel example had a specific constraint: "Do not spend money without my approval." This puts a strict "Permission Gate" (Human-in-the-loop) on the highest level of autonomy.

**Kinds of Tasks:**

- Deterministic Tasks: Given the exact same input, these tasks will **always produce the exact same output**. They follow strict rules, algorithms, or mathematical formulas. There is no randomness, ambiguity, or variability.
- Indeterministic **(Non-Deterministic)** Tasks: Given the exact same input, these tasks can **produce different outputs** on different runs. They involve probability, natural language, dynamic external data, or human judgment.

**Progressive Build:**

1. LLM only
2. Live information
3. Tools
4. Validation
5. Permissions
6. Failure recovery

**Example of Agent "Travel Agent":**

User -> Chat Trigger -> Travel Agent: Web search "read" – Hotel search "read" – Travel time/ maps "read" – Calculator "deterministic" – Booking tool "write" -> Human Approval -> Final Itinerary plan

User Request: "Plan 4 days in Dubai + Abu Dhabi for 2 adults under \$2,000. Hotel + Museum of the Future + Louvre Abu Dhabi + desert experience. Minimize unnecessary travel. Do not spend money without my approval."

**Examples from your "Travel Agent" Scenario**

**1\. Deterministic Tasks (Predictable, rule-based)**  
In your example, the **Calculator** is explicitly labeled as deterministic. Other deterministic tasks in this workflow might include:

- **Budget Validation:** Checking if (Hotel Cost + Flight Cost + Activity Costs) <= \$2,000. The math is absolute.
- **Date Validation:** Checking if the proposed travel dates are in the future.
- **Currency Conversion:** Converting \$2,000 USD to AED using a locked, specific exchange rate.
- **Database Lookup:** Retrieving a specific booking confirmation number using an exact ID.

**2\. Indeterministic Tasks (Variable, context-dependent)**  
In your example, **Web search, Hotel search, Travel time/maps, and Booking tool** are all marked as "read" or "write." These interact with the outside world and are therefore indeterministic:

- **Web Search ("read"):** Searching "Best desert safaris in Abu Dhabi." The search engine results will vary based on the time of day, your location, SEO changes, and trending articles.
- **Hotel Search ("read"):** Searching for hotels. The results depend on real-time availability, dynamic pricing algorithms, and cancellations.
- **Travel Time/Maps ("read"):** Calculating travel time between the Louvre Abu Dhabi and the desert experience. This will vary depending on real-time traffic, road closures, or time of day.
- **LLM Itinerary Generation:** The core AI writing the final itinerary. If you run the prompt twice, the LLM might suggest slightly different wording, different restaurant recommendations, or a different order of activities.
- **Human Approval ("write"):** The final step in your workflow. Human behavior is inherently indeterministic. The user might approve immediately, ask for changes, or reject the plan entirely.

The core challenge of building an AI agent is that **you cannot control indeterministic tasks with deterministic logic.**

- You can't just say "if the web search returns X, do Y."
- This is why **Validation** (step 4) is critical. For indeterministic tasks, validation means checking constraints (e.g., "Is the total cost under \$2,000?").
- This is also why **Human Approval** (step 5) is needed for indeterministic "write" actions (like actually booking the hotel), because the AI cannot guarantee a perfect outcome when interacting with a variable, real-world system.

So, deterministic tasks handled as functions by agent no tin the LLM. Agent is worker do a task then return to the LLM or the orchestrator informs it what It does then LLM decides what is the next step with which tool or agent.

The moment you go live, the problem changes.

These are important aspects in production:

- Explicit state
  - Explicit state must be preserved in Database not in memory.
  - Data per user.
  - State Management.
- Validation
  - Sanitization
- Permissions
  - Human in the loop
  - Don't grant all permissions for AI agent.
- Retries + timeouts
- Idempotency
  - Very important principle in system design.
  - Repeating the same request does not create an additional effect.
  - Where it matters:
    - Payment
    - Booking
    - Email
    - Ticket Creation
    - Account Provisioning
  - Don't do it twice. Retries are easy while safe retries are not.
  - Bad Retry:
    - **The Flow:** 1. The Agent triggers the Book Hotel action. 2. A network **TIMEOUT** occurs. The agent doesn't get a confirmation. 3. The agent thinks, _"Maybe it failed?"_ (This is the critical error in logic). 4. The agent blindly triggers Book Hotel AGAIN.
    - **The Consequence:** x2 TWO BOOKINGS.
    - **Why it's bad:** A timeout does _not_ mean the action failed. It simply means the agent didn't receive the confirmation in time. The original request might have successfully processed on the server before the connection dropped. Blindly retrying creates a **duplicate side effect** (in this case, double-booking the hotel and likely double-charging the user).
  - Safe Retry:
    - **The Flow:** 1. The Agent triggers the Book Hotel action, but this time it includes a unique **Idempotency Key** (shown as request_id: TRIP_001_HOTEL_01). 2. A network **TIMEOUT** occurs. 3. Instead of blindly retrying, the agent uses a tool to Check Booking Status using that same unique request_id. 4. **Decision Point ("Already booked?"):** - **YES:** The system finds the original successful booking. The agent selects Continue, knowing the task is complete. - **NO:** The system confirms no booking exists. The agent safely retries the action via the Retry safely path.
    - **The Consequence:** No duplicate bookings. The system self-corrected safely.
- Observability
  - Done by Telemetry, logs.
  - Each execution for each node must be treacle and have tool that collect all this data in readable format and notify you when you go beyond the boundaries like tokens consumption, response time boundaries.
  - Any boundary you need to keep it safe in your system; put observable layer on it, put notifier on it. This can done easily using cloud watch, AWS, Azure.
- Evals
  - Evaluate values greater than or less than a specific value by putting constraints on variables to make sure user restricts to a specific domain of inputs, and if user exits these domain system pause to prevent any manipulation in the system.
- Rate limits
  - To prevent any bots. Any button in the interface must have a rate limiter in the background and if there any multiple inputs per second the system should disqualify the Ip that the request comes from it.
- Cost limits
  - Tokens consumption.
  - There is difference between deterministic AI Agents, and LLM.
  - Agents theoretically don't consume tokens. The tokens are consumed from the translation of human readable text to JSON like in our travel agent:
    - I need go to Dubai -> city: Dubai
    - I am 34 years old -> age: 34
    - The trip will be form 1 September to 5 September -> start-date: 1 September, end-date: 5 September, duration: 5 days
  - During all this time I keep building JSON that will be sent as a request to a function which in role will implement some steps and retunes response. This response returns to AI that put it in human readable format.
  - Agent is worker not AI. So, it is pointless to put tasks AI Agent can do in nodes or AI that consumes tokens. You can implement this as a separate code as a function that executes these steps then after finishing return to main workflow, and parts that you need in it to return to web search or AI put it in node that consumes tokens and things like rendering, frontend stuff, evaluation, retries, timeouts; all these are logic you can make it by your own don't give it to AI that consumes money.
- Versioning
- Security
  - Security preaches are coming from within by giving agents permissions it shouldn't granted.
- Concurrency
  - Run agents in series or in parallel.

When plan for a new system see failure first what can fail the system as the happy scenario is the easiest scenario

A demo proves it can work. Production proves it can fail safely.

Agents decide. Workflows enforce.

Episodic Memory

N8n from tools that make agent orchestration, and agent workflows.

Setup evaluation for the workflow in n8n; you can put restrictions on every node in your workflow.

Observability entity in executions logs of workflow

What can go wrong with the travel agent if you want to expand or go production?

A lot of edge cases are not handled, model quota could be limited and there is notification inform me I am going out of credits, no error nodes in the workflow; I leave myself to the AI agent without any validation.

We need to know the tokens consumed from AI model. In LangSmith for each runnable sequence it informs you about the tokens consumed and the cost.

Stress Testing

Observability layers on AI Agent observe the systems also consumption of tokens in the agent besides scaling the tokens consumed per user request "pricing per user request".

Latency issues in production also happens.

**DESIGN FOR FAILURE BEFORE YOU DESIGN FOR AUTONOMY.**

This means you cannot just build a system that works perfectly in a "Happy Path" demo. Real-world APIs crash, users give conflicting instructions, and LLMs hallucinate.

| FAILURE                          | RESPONSE                                                                                                                                                                                                                                                                                                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Current information hallucinated | Use live tool + source validation<br><br>If the agent makes up current information (like a fake hotel price), the solution is to force it to use **live tools** (web search, APIs) and validate the sources.                                                                                                                                               |
| API 503 / rate limit             | Bounded retry + exponential backoff + fallback<br><br>If a tool crashes or you hit a rate limit, don't spam the API. Use a **bounded retry** (retry a set number of times), **exponential backoff** (wait 1 second, then 2, then 4, then 8 to give the server time to recover), and a **fallback** (use a different API or tool if the primary one fails). |
| Booking request times out        | Do not blindly retry – check status via idempotency key<br><br>This directly references the previous slide. If a booking times out, do not blindly retry. You must **check the status** using the unique request_id (idempotency key) first to see if the booking actually went through.                                                                   |
| Two sources disagree             | Prefer authoritative source, otherwise flag uncertainty<br><br>If a blog says a museum is open, but the official website says it's closed, the agent should **prefer the authoritative source** (official website). If there is still no clear answer, it should **flag the uncertainty** to the user rather than guessing.                                |
| Agent keeps researching forever  | Max iterations + time budget + cost budget stop condition<br><br>An agent might get stuck in a loop, endlessly searching for better flights. The solution is hard-coded limits: **Max iterations, time budget, and cost budget.** Once it hits the limit, it must stop.                                                                                    |
| Irreversible / sensitive action  | Human approval<br><br>For high-stakes actions like spending money or deleting data, you must use **Human Approval** (Human-in-the-loop). This is the ultimate "Stop Condition."                                                                                                                                                                            |

A GOOD AGENT KNOWS **WHEN** TO STOP.

**DO NOT:**

- give every tool unrestricted permission
- retry transactional actions blindly
  - Tell the agents that upon failure check on a specific variable state instead of retrying forever.
- let the LLM invent missing tool results
  - If tool failed don't make LLM orchestrator, do it on it behave.
  - Put boundaries to the AI orchestrator in dealing with agents and within user flow
- hide failures behind a pretty final answer
- create 8 agents when one agent + 3 functions is enough
  - Separate between things I really need AI to do like somethings need reasoning, indeterministic based on user preferences and just deterministic tasks "functions/ facts" known that tool can do.

**SCALE THE SYSTEM. NOT THE PROMPT.**

Many AI developers fall into the trap of thinking that if they just write a better prompt, their agent will magically become faster, cheaper, and more reliable. **scaling an AI agent is a software engineering problem, not a prompt engineering problem.** You cannot prompt your way out of a system that crashes under load, leaks credentials, or double-books hotels.

**When you build a real system, this going to be the INFRASTRUCTURE (Real-system Infrastructure) "**production-grade scalable architecture for an AI workflow**":**

- incoming users / API calls
  - Do the map of how many these API calls going to be done.
  - Multiply number of user on number of API calls on every workflow execution instance so you know the usage scale/ size of your system and based on this decide the infrastructure of your business.
- LOAD BALANCER
- WEBHOOK PROCESSORS
- n8n MAIN: This is the brain. It receives the request but does not do the heavy lifting itself. Instead, it pushes tasks into a queue.
- REDIS QUEUE: This is the buffer. If 1,000 users ask for a travel itinerary at the same time, the Redis Queue holds those requests so the system doesn't crash. It processes them based on available capacity.
- WORKER POOL: The actual processing happens here. Multiple **Workers** pull tasks from the queue and execute the workflow. If traffic increases, you simply add more workers (horizontal scaling).
  - worker | worker | worker
- POSTGRESQL: The system state, user data, and execution logs are stored here. (Note: The bottom text emphasizes **External Storage, Observability/Tracing, and Secrets**—these are critical supporting infrastructure components).
- _Bottom row:_ EXTERNAL STORAGE | OBSERVABILITY / TRACING | SECRETS

**The Golden Rule:** _"n8n is the orchestrator. Your production architecture is still your responsibility."_ Just because n8n manages the workflow doesn't mean it manages the servers, security, or database scaling.

**WORKFLOW LAYER "Our Travel Agent example"**

- TRAVEL AGENT
- READ TOOLS
- VALIDATION
- HUMAN APPROVAL
- TRANSACTIONAL TOOLS
- _Text below:_ n8n is the orchestrator. Your production architecture is still your responsibility.

**DO**

- Separate dev / production
- Use queue + workers as load grows
- Control concurrency
- Use Postgres for distributed deployment
- Monitor failures + latency + costs
- Prune unnecessary execution data
- Version workflows
- Protect credentials
- Run security audits
- Back up state

**DON'T**

- Run distributed production on SQLite
- Put unlimited concurrency everywhere
- Save every execution forever
- Expose production credentials in prompts
- Let agent-generated input bypass validation
- Deploy workflow edits directly from experiments
- Put irreversible tools behind no approval gate

**MATURITY PATH: n8n IS A STARTING POINT. NOT THE ARCHITECTURE.**

When complexity grows, move the right parts into code and infrastructure.

**The Maturity Levels:**

- **Level 1 (n8n):** The Prototype phase. You use n8n for everything: the agent logic, the AI tools, and the workflow. It's fast to build and easy to change.
- **Level 2 (n8n + Custom Services):** The Hybrid phase. You realize n8n isn't great at certain tasks (like complex database queries or custom validation), so you write **Python/Node APIs** to handle those specific pieces, while n8n still orchestrates the overall flow.
- **Level 3 (Agent Runtime / Orchestration):** The Framework phase. As the agent's logic gets too complex for visual nodes, you migrate to dedicated AI orchestration frameworks like **LangGraph, OpenAI Agents SDK, Google ADK, Microsoft Agent Framework, or Agno**. Here, you start managing state, validation services, and custom tools in code.
- **Level 4 (Production Platform):** The Enterprise phase. You are now building a full-fledged software platform. You use **API Gateways, Workers, Queues, Databases, Caches, Observability, Secrets management, Policy Engines, and Human Approval** steps. This is distributed, scalable, and secure.

### ⚖️ The "Keep vs. Move" Decision Matrix

How do you know when to abandon n8n for a specific feature? The slide provides a clear checklist:

**🟢 KEEP n8n FOR:**

- Visual orchestration
- Integrations (connecting to 3rd party APIs)
- Approvals (Human-in-the-loop)
- Simple workflows
- Automation
- Prototypes

**🔴 MOVE TO CODE WHEN:**

- State becomes complex
- Latency matters
- High concurrency
- Advanced retry logic (like the idempotency and exponential backoff we discussed)
- Custom algorithms
- Complex branching
- Strict testing
- Transactional consistency
- Reusable internal services

**"DON'T REWRITE EVERYTHING"**: The path from n8n to a full production platform should be an evolution, not a revolution. You don't wake up one day and throw n8n in the trash. You incrementally move pieces to code, then to an agent SDK, then to queues and APIs, as the need arises.

**"USE THE SIMPLEST ORCHESTRATOR THAT CAN SAFELY RUN THE SYSTEM."**: This is the ultimate guiding principle. Don't build a Level 4 distributed production platform if a simple Level 1 n8n workflow can do the job safely. Complexity is a cost, not a badge of honor.

Before calling your workflow an "agent," you must be able to answer these nine questions. They are grouped into three core areas:

**1\. Purpose & Capabilities (01, 02, 03)**

- **What is the goal?** The goal of your agent. (e.g., "Plan a 4-day trip under \$2,000.")
- **What may it decide?** (e.g., It can choose hotels, but it cannot choose to book a flight outside the budget.)
- **What tools may it use?** (e.g., Web search, Calculator, Booking API). This defines the agent's "hands." That do a deterministic task.

**2\. Memory & Validation (04, 05)**

- **What state must persist?** (e.g., The user's budget and preferences must be remembered and preserved across the entire conversation, so it doesn't forget them halfway through).
- **How is output validated?** Either manual or automatic testing/ validation (e.g., If the LLM generates a total cost, a deterministic calculator must verify it matches the budget _before_ showing the user).

**3\. Failure Engineering & Safety (06, 07, 08, 09)**

- **What can go wrong?** (e.g., API timeouts, hallucinations, conflicting hotel prices).
- **What requires a human?** (e.g., Spending money. This is the "Human-in-the-loop" approval gate).
- **How does it recover?** (e.g., Using idempotency keys to check booking status instead of blindly retrying).
- **What makes it STOP?** This is the most critical question. An agent without a stop condition is a runaway train. Stop conditions include max iterations, time budgets, cost budgets, or hitting an irreversible action that needs human approval.

**THE MODEL IS NOT THE SYSTEM.**

Many people think that because they have access to a powerful Large Language Model (like GPT-4), they have an autonomous agent. Model is just a component—like a CPU. The system is the infrastructure, the safety rails, the validation logic, and the orchestration around that model. The real engineering starts where the demo stops working. Demos work on the happy path; production systems must handle the chaos of the real world.

**Search More:**

- n8n setup evaluation
- n8n execution observability
- integrate n8n with lovable
- trigger workflows in n8n
- observability layer ai

**Tools:**

- langsmith
- bedrock
- telemetry
- langgraph

**Resources:**

- [https://www.youtube.com/watch?v=GuaKeDS6UKU&t](https://www.youtube.com/watch?v=GuaKeDS6UKU&t=1s)
- <https://www.youtube.com/watch?v=4wsV1GgIsrs>
- <https://www.youtube.com/watch?v=lW5xEm7iSXk>

**AAW Webinar 03 — Agents for Non-Techies**

Make your own philosophy of using AI

Learn by doing "practice"

Agent = Harness + AI Model + Tools

Hermes Agent Advantages:

- Permanent memory across all sessions
- You can add/ download skills to it and these skills develop with you according to your usage, and notes you give to it during using it in the sessions.

There are two ways to use Intelligence of AI model the first by API calls and the other which Open Ai and Claude offer that you can take its model itself and use it in whatever harness you need

English or Arabic whatever is your language is the new programming language

The trend now is not about prompting is about are you capable to ask exactly what you need or not

**Discussions:**

- No code automation tools/ SASS is dead.

**Search Later:**

- Telegram Mini App
- harness ai
- AI Slop
- Frontier models
- Hermes Agent
- How to install models in my local
- <https://www.make.com/en>
- LangFlow
- <https://zapier.com/>
- How to make agent build agent