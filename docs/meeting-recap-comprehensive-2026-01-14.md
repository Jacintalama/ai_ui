# Comprehensive Meeting Recap - January 2026

## Executive Summary

| Priority | Description |
|----------|-------------|
| **Project Deployment** | Prioritize running Open Web UI app locally with Docker and set up a shared environment by week's end |
| **Data Security** | Aim for strict data separation in multi-tenant architecture supporting 15,000 employees from clients like Google and Microsoft |
| **Daily Stand-Ups** | Implement 15-minute meetings at 9:30 PM for updates, avoiding micromanagement and promoting autonomy in work hours |
| **Resource Management** | Weekly autopay via Wise starts January 16th; team to provide details for setup and begin with a $21/month Cloud Code plan |
| **Innovation Focus** | Encourage engineers to innovate within their fields, avoiding lengthy stakeholder input and fostering a flexible project roadmap |
| **Risk Management** | Address technical challenges with MCP protocols and require immediate escalation of blockers via WhatsApp for quicker resolutions |

---

# Meeting 1: Project Setup and Initial Deployment

## Project Setup and Initial Deployment

The team agreed to prioritize getting the Open Web UI app running locally using Docker with one command as the initial success milestone (00:19).

- Lukas Herajt explained the need for running the app locally to test integration with MCP servers, which is key to the project's goals
- Setting up a shared deployed environment by the end of the week was committed to, to enable collaborative testing and visibility of changes
- The focus is on integrating 70 MCP servers, some requiring proxy servers due to streaming protocols, which adds complexity to deployment
- Lukas assigned Jacint Alama and Jumar James Juaton to start familiarizing themselves with the app and MCP server integration based on their specialties
- The project involves a multi-tenant architecture serving 15,000 employees across clients like Google and Microsoft, requiring strict data separation and permission controls (00:21)

### Technical Challenges Identified

- Lukas identified access and permission handling as the biggest technical challenge, emphasizing the need for tenant isolation in integrations like JIRA/Atlassian
- Research into API gateways and custom server registries to manage permissions is ongoing but still incomplete
- The system is deployed on Kubernetes for scalability but requires better error handling for protocols like SSE to ease debugging

---

## Team Communication and Work Rhythm

The team decided on a daily 15-minute stand-up at 9:30 PM via Google Meet to share updates, blockers, and accomplishments (00:11).

- Clarenz Bacalla will compile these daily updates and report weekly to Lukas to maintain project oversight despite his busy schedule
- The stand-ups are designed to avoid micromanagement; no time tracking is required, and team members have full flexibility on work hours
- Daily End-Of-Day (EOD) reports with to-dos, progress, accomplishments, and blockers will be shared in a WhatsApp group for transparency and quick communication
- WhatsApp was chosen as the primary communication channel for urgent matters, due to Lukas's slower email response times
- Lukas emphasized a culture of autonomy and responsibility, encouraging engineers to take ownership of their specialty areas and propose integrations or automations that add value (00:32)
- He expressed a preference for developers to focus on what they enjoy and avoid tasks like styling, which he dislikes and views as unproductive
- The team will avoid unnecessary meetings beyond the daily stand-up to maximize focus time

---

## Resource Management and Tools

Lukas arranged for weekly autopay via Wise, starting January 16th, to ensure consistent and timely compensation for the engineers (00:04, 00:29).

- Team members were asked to provide their Wise account details for autopay setup
- Lukas also committed to providing a credit card for Cloud Code accounts, the AI-powered coding tool he prefers, due to its superior capabilities despite cost concerns (00:10)
- The team agreed to start with the $21/month Cloud Code plan, with the option to upgrade based on usage and Lukas's company budget constraints
- Cloud Code's mini MCP features were noted as valuable for brainstorming and coding productivity

---

## Project Vision and Strategic Direction

Lukas described the project as a flexible internal tool for 15,000 employees with multiple clients, aimed at enabling integration with various LLM models and third-party services while maintaining data security and multi-tenancy (00:30).

- The strategic goal is to provide autonomy to the software engineers to innovate within their fields and integrate value-adding features
- He stressed the importance of building a product that can scale and adapt easily, avoiding long delays caused by excessive stakeholder input and micromanagement
- The project roadmap is fluid, with optimistic but uncertain deadlines, reflecting ongoing client requirements refinement and onboarding of new team members (00:25)
- The emphasis is on delivering practical automation and middleware capabilities that clients may not fully understand yet

---

## Operational Challenges and Risk Mitigation

Lukas acknowledged several technical challenges, including complex protocol handling for MCP servers and lack of error messaging that complicates debugging (00:22).

- The protocol diversity (HTTP, SSE streaming) requires proxy server solutions, increasing deployment complexity
- Lack of clear client requirements and shifting priorities pose risks to timeline predictability and scope stability
- The team agreed to escalate blockers immediately via WhatsApp to minimize downtime, with Lukas available from 2 PM to 6 AM Philippine time for technical support (00:24)
- Clarenz's role focuses on project coordination and progress tracking, avoiding technical tasks to maintain clear accountability boundaries

---

## Team Culture and Engagement

The team established a friendly, open culture emphasizing flexibility and mutual support, reflected in informal discussions about locations and personal interests (00:06–00:45).

- Lukas shared his motivation for moving to the Philippines to enjoy a better work-life balance, which informs his management style focused on autonomy and trust
- The team agreed on no micromanagement or time tracking to foster productivity and satisfaction
- Lukas expressed enthusiasm for working with passionate software engineers and expects the team to self-direct their work while maintaining alignment through daily stand-ups and EOD updates

---

## Action Items - Meeting 1

### Lukas Herajt
- [ ] Send detailed instructions on how to add MCP servers to the Open Web UI app (34:45)
- [ ] Provide credit card for Jumar and Jacint to set up Cloud Code accounts (10:30)
- [ ] Schedule autopay payments via Wise starting January 16th for weekly payments and confirm Wise handles from Jumar and Jacint (04:23)
- [ ] Set up shared deployed environment for app testing and collaboration by end of the week to track changes and MCP server integration (34:55)
- [ ] Schedule daily 15-minute standup meetings at 9:30 PM on Google Meet; send meeting link to team (13:00)
- [ ] Monitor blockers and provide technical unblocking support during working hours (15:30)

### Jacint Alama
- [ ] Run Open Web UI application locally using Docker and get familiar with the codebase by tomorrow standup (19:45)
- [ ] Share WhatsApp contact in the group chat for communications (03:10)
- [ ] Setup Wise account handle in chat

---

# Meeting 2: Infrastructure and Technical Progress

## Key Progress Summary

| Area | Status | Details |
|------|--------|---------|
| **MCP Server Deployment** | In Progress | Team is deploying using Docker and Kubernetes for scalable infrastructure |
| **Docker Progress** | Working | Jumar fixed errors; Docker works for consistent Node versions |
| **Kubernetes Challenges** | Needs Work | Existing complex setups hinder deployment; switching to standard helm charts recommended |
| **User Access Management** | Tested | Permission controls tested successfully; focus on resolving access issues |
| **Community Tools Integration** | Exploring | Exploring community-built tools to accelerate development |
| **Shared Documentation** | Planned | A shared spreadsheet will log ongoing work and integration challenges |

---

## Infrastructure and Deployment

The team is progressing on deploying the MCP server using Docker and Kubernetes, aiming for scalable, multi-tenant infrastructure (00:00).

### Docker Progress
- Docker is confirmed functional by Jacint and Jumar, with Jumar currently fixing MCP server errors while successfully running the server (00:00)
- Lukas highlighted Docker's advantage in keeping consistent Node versions across all developers
- MCP server error handling remains difficult due to vague error messages, impacting debugging speed
- Planned deployment of the MCP server repository is expected by today or tomorrow to enable a shared environment
- The team is encouraged to experiment with GitHub and other MCP servers for hands-on familiarity

### Kubernetes Deployment
- Kubernetes deployment is underway but faces challenges from existing infrastructure setups that are incompatible with Open Web UI (00:05)
- Lukas explained the existing infrastructure guy set up a complex, multi-database Kubernetes system unsuitable for Open Web UI's single-database requirement
- Lukas recommended discarding the custom Kubernetes setup in favor of standard Open Web UI helm charts for easier scaling and maintenance
- Jacint is studying Kubernetes to align with deployment needs, targeting infrastructure that can scale for 15,000 users
- The current custom Azure Kubernetes infrastructure is functional but suboptimal, risking future scalability and compatibility

---

## User Access and Permissions Management

Managing multi-tenant user access through Web UI permission controls is advancing, with initial user and group setups underway (00:08).

- Jacint successfully tested user permission controls allowing assignment of groups access to specific models and MCP servers (00:08)
- Issues remain where some test users see no available models, likely due to missing OpenAI API keys or permissions set at the model or group level
- Lukas emphasized the ease of using checkbox-based permission management in the admin UI, avoiding code changes
- This permission system is critical for enabling isolated access for multiple clients in a multi-tenant environment
- Jacint plans to resolve user model access issues by tomorrow to fully enable user role testing
- The team is encouraged to create multiple user accounts beyond admin to test real-world permission scenarios and access segregation
- Lukas noted that OpenAI models appear in dropdowns only after adding valid API keys, which must be managed carefully

---

## Community Tools and Integration Strategy

Exploring community-built tools and pipelines is a key strategy to accelerate development and integration with MCP servers (00:02).

- Lukas shared a community tools repository with various middleware and pipelines that can trigger workflows and integrate with Open Web UI (00:02)
- These tools typically use Python, enabling quick reuse instead of rebuilding functionality
- Examples include pipelines for Kubernetes operations and communication triggers
- The team is encouraged to explore these tools to extend capabilities and reduce development time
- Integration plans focus on connecting Open Web UI to existing MCP-compatible services like Trello, Notion, and Todoist to build practical workflows (00:10)
- Lukas suggested experimenting with these services on personal accounts to gain familiarity
- The long-term goal is to support multiple MCP servers and protocols, enhancing the platform's flexibility

---

## Documentation and Collaboration Processes

Improving transparency and coordination through shared documentation is planned to track progress and technical findings (00:13).

- Clarenz proposed creating a shared spreadsheet by week's end to log ongoing work, important issues, and progress updates for team calibration (00:13)
- Lukas supported this, highlighting the importance of documenting integration challenges, such as MCP protocol incompatibilities
- For example, the team encountered a protocol mismatch with Atlassian's MCP server that uses SSE instead of streaming, which Open Web UI supports
- This documentation will prevent repeated roadblocks by sharing "workarounds" and integration insights
- The spreadsheet aims to be a simple interim solution for team visibility until more formal tools are set up

---

## Technical Challenges and Learning Progress

The team is actively learning and troubleshooting technical challenges around Docker, Kubernetes, and MCP server integration (00:00-00:12).

### Docker and Platform Issues
- Debugging the MCP server and Docker on different platforms is proving complex but manageable (00:00)
- Jumar noted the ease of getting Docker running after initial errors
- Lukas described the challenges of running Docker on Apple M1 hardware, requiring Rosetta translation for compatibility
- Maintaining consistent development environments using Docker helps avoid "works on my machine" problems

### Kubernetes Knowledge
- Kubernetes knowledge gaps are being addressed through individual study and exploration (00:07)
- Jacint is deepening his knowledge to support proper deployment aligned with product needs
- Lukas recommended standard Open Web UI Kubernetes helm charts for simpler, scalable deployment

### User Model Issues
- User model visibility issues are a current focus area for troubleshooting (00:03)
- Jacint is working to resolve confusion around user creation and model access permissions
- Lukas explained the dependency on valid API keys to populate available models for users

---

## Next Steps and Strategic Focus

The main goals are to deploy a shared MCP server environment, enable robust user access controls, and integrate community tools for practical workflows (00:11).

- Lukas tasked the team with familiarizing themselves with Open Web UI, MCP servers, and community tools to build hands-on experience (00:11)
- Jumar expressed enthusiasm about exploring these components
- Regular update notes are encouraged to keep leadership informed of progress and blockers
- The team will continue working on user permissions, Docker stability, and Kubernetes deployments with expected completions within the next few days
  - Jacint will address user access issues by tomorrow
  - MCP server deployment is targeted for today or tomorrow
  - Exploration of community tools for workflow triggers is ongoing
- Documentation of integration challenges and solutions will be centralized in the shared spreadsheet to streamline knowledge sharing and avoid repeated issues (00:13)
- This process supports continuous improvement and quicker onboarding for new team members
- The team agreed to meet again the following day to review progress and coordinate next steps

---

## Action Items - Meeting 2

### Jacint Alama
- [ ] Continue working on resolving user creation and model access issues in the admin interface (09:00)

### Jumar James Juaton
- [ ] Fix errors on the MCP server and continue exploring Open Web UI features (00:50)

### Clarenz Bacalla
- [ ] Create and share a collaborative spreadsheet to log ongoing work, issues, and important notes for team calibration by the end of the current week or early next week (13:40)

### Lukas Herajt
- [ ] Deploy Open Web UI repository and shared environment including API key setup, targeted for today or tomorrow (01:30)
- [ ] Monitor team's progress with Docker, Kubernetes, and permissions; support with incremental upgrades as needed (11:40)
- [ ] Document MCP server protocol incompatibility issues and solutions related to Atlassian integration for team reference (14:10)

---

# Meeting 3: GitHub Integration and Architecture

## Key Achievements

| Achievement | Description |
|-------------|-------------|
| **GitHub MCP Integration Success** | Integrated GitHub MCP server enables AI to list repositories, enhancing repository access and code analysis |
| **MCP Server List Development** | Curated list of priority MCP servers will streamline integration, focusing on protocol compatibility and quick wins |
| **Local LLM Deployments** | Testing local LLMs, like Ollama, mitigates data privacy risks and addresses compatibility issues for code analysis features |
| **File Access Implementation** | Local file system access is crucial for deeper repository analysis, allowing sandboxed code execution and enhancing accuracy |
| **Knowledge Sharing Systems** | Initial use of spreadsheets for documentation will transition to Jira for better collaboration and streamlined accountability soon |
| **Secure Multi-Tenancy Architecture** | Using Postgres with row-level security and Microsoft Entra IDs ensures data isolation and simplifies authentication across tenants |

---

## GitHub and MCP Server Integration

The team made solid progress integrating GitHub and exploring MCP server options to streamline API key management and repository access.

### GitHub Integration Success
- Jacint Alama successfully integrated GitHub MCP server support, enabling AI to list all repositories using the API key from a configured MCP server (01:06)
- Jacint is still investigating which MCP server URL to use, balancing between the popular Smither AI server and the official GitHub MCP server
- Lukas explained that both MCP servers rely on API keys but differ in focus: the official one targets coding tools, while others may be better for LLM integrations
- This integration supports secure access and will help automate repository listing and code analysis across tenants
- The decision to start with simpler HTTP protocol MCP servers aims to accelerate integration before tackling more complex servers needing proxy setups

### MCP Server Strategy
- Lukas outlined a plan to curate and share a prioritized list of MCP servers based on protocol compatibility, targeting quick wins with HTTP-supporting servers (08:16)
- This list will help the team focus on servers that work out of the box with the open web UI, avoiding streaming or SSE protocol issues initially
- Sharing this list on WhatsApp provides a centralized source for integration progress and helps coordinate future proxy server architecture
- The proxy design will handle authentication and authorization via Microsoft Entra ID tokens, ensuring tenant-level access control
- Lukas emphasized the importance of balancing protocol variety with a unified API gateway for security and scalability

---

## Local LLM Deployments and Testing

The group is validating multiple local LLM setups to support AI-driven code analysis and chatbot features while protecting client data.

### Testing Progress
- Jumar James Juaton tested several LLMs locally, including Ollama via Docker and OpenAI-compatible APIs, gaining hands-on experience with different setups (04:22)
- Running LLMs locally avoids sending sensitive data to the cloud, reducing compliance risks
- Ollama was noted as the easiest to set up, while others like VLLM are newer and less familiar
- Lukas highlighted occasional compatibility challenges with function calling and protocol support among LLMs and MCP servers, influencing model selection
- This testing phase informs which LLMs will be best suited for code analysis and chat features in the product pipeline

### Dual-Model Strategy
- The team intends to focus on ChatGPT for general AI chat functions and OPUS or Sonnet models for code analysis, hosted locally for data privacy (11:30)
- This dual-model approach aims to optimize user experiences by matching AI capabilities to specific tasks
- Local hosting mitigates client data leakage and reduces dependency on external cloud services
- Strategic use of different LLMs supports modular and flexible AI service architecture
- Lukas encouraged ongoing exploration of Kubernetes and infrastructure options to scale these models efficiently

---

## File System Access and Code Analysis Enhancement

File system integration is identified as a crucial next step to enable sandboxed code execution and deeper repository analysis.

- Jumar James Juaton began implementing local file system access for listing files and directories, complementing MCP server repository data (12:34)
- This capability is necessary to run cloud code analysis tools in sandbox environments using actual project files
- Lukas stressed that combining file system access with GitHub MCP server integration enables full repository retrieval and dynamic code evaluation
- This step addresses current limitations where code analysis requires file-level data beyond API metadata
- The expected outcome is improved accuracy and depth in automated code reviews and developer tools

---

## Process Documentation and Knowledge Sharing

The team prioritized establishing a shared system for documenting integration research and technical findings to enhance collaboration.

- Clarenz Bacalla proposed using spreadsheets initially for knowledge sharing before migrating to Jira or Trello, balancing simplicity and tool availability (14:32)
- Spreadsheets allow quick input of URLs, API keys, connection details, and screenshots without subscription barriers
- Lukas agreed, emphasizing the need for a single source of truth to track MCP server URLs, API key setups, and integration notes
- Once the research repository is stable, the team plans to transition to Jira for issue tracking and ticket assignments to streamline accountability
- This documentation effort will accelerate onboarding and reduce duplicated research effort across team members

---

## Authentication and Multi-Tenancy Strategy

Securing multi-tenant environments and simplifying authentication were key architectural topics discussed.

### Database Architecture
- Lukas described the use of a Postgres database with PGvector and row-level security keyed by workspace ID, which acts as tenant isolation (07:08)
- This design prevents cross-tenant data access and supports group-based permission management within each workspace

### API Gateway and Entra ID
- The team is exploring an API gateway approach combined with Microsoft Entra ID token authentication to control access to MCP servers and APIs (09:53)
- This unified authentication method aligns well with the Microsoft ecosystem and provides a scalable security model
- Future proxy servers will handle protocol differences transparently while enforcing authorization based on Entra ID claims

### Separation of Concerns
- The approach ensures separation of concerns between client data, authentication, and protocol handling, reducing operational risks and complexity (09:53)
- This design supports onboarding multiple clients with distinct access needs without creating separate databases
- It also allows the team to centralize logging, monitoring, and permissions enforcement in the API gateway layer
- The strategy aims to balance security, scalability, and ease of integration for various MCP server technologies
- Lukas encouraged team input on improving or simplifying this architecture as they gain more experience

---

## Action Items - Meeting 3

### Lukas Herajt
- [ ] Refine and share the list of MCP servers prioritizing HTTP protocol integrations by end of day (08:16)
- [ ] Aim to deploy the system instance by end of the week to enable testing and further development (13:36)
- [ ] Share updated MCP server list with team via WhatsApp for easy reference and ordering tasks (08:16)

### Jacint Alama
- [ ] Continue exploring Kubernetes tech and tenancy separation using workspace IDs and PostgreSQL as discussed (06:40)
- [ ] Update the shared documentation with details on GitHub MCP server URL used and configuration steps to aid team knowledge base (13:36)

### Jumar James Juaton
- [ ] Progress on file system access feature: test and confirm MCP server file listings and directory access for local code analysis (12:34)
- [ ] Document findings on MCP servers including connection types and performance characteristics for shared team tracking (13:36)

### Clarenz Bacalla
- [ ] Set up a shared platform (start with spreadsheet) to collect and organize MCP server integration research including URLs, API keys, and screenshots (13:36)
- [ ] Facilitate ticket creation and management in Trello or Jira when transitioning from spreadsheet to more formal issue-tracking system (14:32)

---

# Technical Architecture Summary

## Current System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OPEN WEB UI PLATFORM                                 │
│                    (15,000 employees - Multi-Tenant)                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐       │
│  │   Microsoft     │     │   Open WebUI    │     │   MCP Proxy     │       │
│  │   Entra ID      │────▶│   (Frontend)    │────▶│   Gateway       │       │
│  │   OAuth/Groups  │     │                 │     │                 │       │
│  └─────────────────┘     └─────────────────┘     └────────┬────────┘       │
│                                                           │                 │
│                                                           ▼                 │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        MCP SERVERS (70+)                             │   │
│  ├─────────────────┬─────────────────┬─────────────────┬───────────────┤   │
│  │   Tier 1: HTTP  │   Tier 2: SSE   │   Tier 3: stdio │   Local       │   │
│  │   - Linear      │   - Atlassian   │   - SonarQube   │   - GitHub    │   │
│  │   - Notion      │   - Asana       │                 │   - Filesystem│   │
│  │   - HubSpot     │                 │                 │               │   │
│  │   - Pulumi      │                 │                 │               │   │
│  │   - GitLab      │                 │                 │               │   │
│  │   - Sentry      │                 │                 │               │   │
│  └─────────────────┴─────────────────┴─────────────────┴───────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        DATABASE LAYER                                │   │
│  │  PostgreSQL + PGvector with Row-Level Security (Workspace ID)       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Entra ID Group-Based Access Control

```
User Login → Entra ID → Groups in Token → Open WebUI → MCP Proxy → Access Check

Groups:
- MCP-GitHub     → github server
- MCP-Filesystem → filesystem server
- MCP-Linear     → linear server
- MCP-Admin      → ALL servers
```

---

# Consolidated Action Items by Person

## Lukas Herajt
- [ ] Send detailed instructions on how to add MCP servers to the Open Web UI app
- [ ] Provide credit card for Jumar and Jacint to set up Cloud Code accounts
- [ ] Schedule autopay payments via Wise starting January 16th
- [ ] Set up shared deployed environment for app testing and collaboration
- [ ] Schedule daily 15-minute standup meetings at 9:30 PM on Google Meet
- [ ] Monitor blockers and provide technical unblocking support
- [ ] Deploy Open Web UI repository and shared environment including API key setup
- [ ] Document MCP server protocol incompatibility issues and solutions
- [ ] Refine and share the list of MCP servers prioritizing HTTP protocol integrations
- [ ] Share updated MCP server list with team via WhatsApp

## Jacint Alama
- [ ] Run Open Web UI application locally using Docker and get familiar with the codebase
- [ ] Share WhatsApp contact in the group chat for communications
- [ ] Setup Wise account handle in chat
- [ ] Continue working on resolving user creation and model access issues
- [ ] Continue exploring Kubernetes tech and tenancy separation
- [ ] Update the shared documentation with GitHub MCP server configuration steps

## Jumar James Juaton
- [ ] Fix errors on the MCP server and continue exploring Open Web UI features
- [ ] Progress on file system access feature: test MCP server file listings
- [ ] Document findings on MCP servers including connection types

## Clarenz Bacalla
- [ ] Create and share a collaborative spreadsheet for team calibration
- [ ] Set up a shared platform to collect MCP server integration research
- [ ] Facilitate ticket creation and management in Trello or Jira

---

*Meeting Notes Compiled: January 14, 2026*
*Team Lead: Lukas Herajt*
*Participants: Jacint Alama, Jumar James Juaton, Clarenz Bacalla*
