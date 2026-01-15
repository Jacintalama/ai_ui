# Meeting Recap - January 14, 2026

## Key Priorities

| Priority | Description |
|----------|-------------|
| **Project Deployment** | Prioritize running Open Web UI app locally with Docker and set up a shared environment by week's end |
| **Data Security** | Aim for strict data separation in multi-tenant architecture supporting 15,000 employees from clients like Google and Microsoft |
| **Daily Stand-Ups** | Implement 15-minute meetings at 9:30 PM for updates, avoiding micromanagement and promoting autonomy in work hours |
| **Resource Management** | Weekly autopay via Wise starts January 16th; team to provide details for setup and begin with a $21/month Cloud Code plan |
| **Innovation Focus** | Encourage engineers to innovate within their fields, avoiding lengthy stakeholder input and fostering a flexible project roadmap |
| **Risk Management** | Address technical challenges with MCP protocols and require immediate escalation of blockers via WhatsApp for quicker resolutions |

---

## Detailed Notes

### Project Setup and Initial Deployment

- The team agreed to prioritize getting the Open Web UI app running locally using Docker with one command as the initial success milestone
- Lukas Herajt explained the need for running the app locally to test integration with MCP servers, which is key to the project's goals
- Setting up a shared deployed environment by the end of the week was committed to, to enable collaborative testing and visibility of changes
- The focus is on integrating 70 MCP servers, some requiring proxy servers due to streaming protocols, which adds complexity to deployment
- Lukas assigned Jacint Alama and Jumar James Juaton to start familiarizing themselves with the app and MCP server integration based on their specialties
- The project involves a multi-tenant architecture serving 15,000 employees across clients like Google and Microsoft, requiring strict data separation and permission controls

### Technical Challenges

- Lukas identified access and permission handling as the biggest technical challenge, emphasizing the need for tenant isolation in integrations like JIRA/Atlassian
- Research into API gateways and custom server registries to manage permissions is ongoing but still incomplete
- The system is deployed on Kubernetes for scalability but requires better error handling for protocols like SSE to ease debugging

### Team Communication and Work Rhythm

- The team decided on a daily 15-minute stand-up at 9:30 PM via Google Meet to share updates, blockers, and accomplishments
- Clarenz Bacalla will compile these daily updates and report weekly to Lukas to maintain project oversight despite his busy schedule
- The stand-ups are designed to avoid micromanagement; no time tracking is required, and team members have full flexibility on work hours
- Daily End-Of-Day (EOD) reports with to-dos, progress, accomplishments, and blockers will be shared in a WhatsApp group for transparency and quick communication
- WhatsApp was chosen as the primary communication channel for urgent matters, due to Lukas's slower email response times
- Lukas emphasized a culture of autonomy and responsibility, encouraging engineers to take ownership of their specialty areas and propose integrations or automations that add value
- The team will avoid unnecessary meetings beyond the daily stand-up to maximize focus time

### Resource Management and Tools

- Lukas arranged for weekly autopay via Wise, starting January 16th, to ensure consistent and timely compensation for the engineers
- Team members were asked to provide their Wise account details for autopay setup
- Lukas also committed to providing a credit card for Cloud Code accounts, the AI-powered coding tool he prefers, due to its superior capabilities despite cost concerns
- The team agreed to start with the $21/month Cloud Code plan, with the option to upgrade based on usage and Lukas's company budget constraints
- Cloud Code's mini MCP features were noted as valuable for brainstorming and coding productivity

### Project Vision and Strategic Direction

- Lukas described the project as a flexible internal tool for 15,000 employees with multiple clients, aimed at enabling integration with various LLM models and third-party services while maintaining data security and multi-tenancy
- The strategic goal is to provide autonomy to the software engineers to innovate within their fields and integrate value-adding features
- He stressed the importance of building a product that can scale and adapt easily, avoiding long delays caused by excessive stakeholder input and micromanagement
- The project roadmap is fluid, with optimistic but uncertain deadlines, reflecting ongoing client requirements refinement and onboarding of new team members
- The emphasis is on delivering practical automation and middleware capabilities that clients may not fully understand yet

### Operational Challenges and Risk Mitigation

- Lukas acknowledged several technical challenges, including complex protocol handling for MCP servers and lack of error messaging that complicates debugging
- The protocol diversity (HTTP, SSE streaming) requires proxy server solutions, increasing deployment complexity
- Lack of clear client requirements and shifting priorities pose risks to timeline predictability and scope stability
- The team agreed to escalate blockers immediately via WhatsApp to minimize downtime, with Lukas available from 2 PM to 6 AM Philippine time for technical support
- Clarenz's role focuses on project coordination and progress tracking, avoiding technical tasks to maintain clear accountability boundaries

### Team Culture and Engagement

- The team established a friendly, open culture emphasizing flexibility and mutual support
- Lukas shared his motivation for moving to the Philippines to enjoy a better work-life balance, which informs his management style focused on autonomy and trust
- The team agreed on no micromanagement or time tracking to foster productivity and satisfaction
- Lukas expressed enthusiasm for working with passionate software engineers and expects the team to self-direct their work while maintaining alignment through daily stand-ups and EOD updates

---

## Action Items

### Lukas Herajt
- [ ] Send detailed instructions on how to add MCP servers to the Open Web UI app
- [ ] Provide credit card for Jumar and Jacint to set up Cloud Code accounts
- [ ] Schedule autopay payments via Wise starting January 16th for weekly payments and confirm Wise handles from Jumar and Jacint
- [ ] Set up shared deployed environment for app testing and collaboration by end of the week to track changes and MCP server integration
- [ ] Schedule daily 15-minute standup meetings at 9:30 PM on Google Meet; send meeting link to team
- [ ] Monitor blockers and provide technical unblocking support during working hours

### Jacint Alama
- [ ] Run Open Web UI application locally using Docker and get familiar with the codebase by tomorrow standup
- [ ] Share WhatsApp contact in the group chat for communications
- [ ] Setup Wise account handle in chat

### Jumar James Juaton
- [ ] Continue fixing MCP server errors
- [ ] Setup Wise account handle in chat

### Clarenz Bacalla
- [ ] Create shared spreadsheet by week's end to log ongoing work, important issues, and progress updates

---

## Technical Progress Update

### MCP Server Deployment
- Team is deploying the MCP server using Docker and Kubernetes for scalable infrastructure
- Docker Progress: Jumar fixed errors; Docker works for consistent Node versions. Error handling is still challenging
- Kubernetes Challenges: Existing complex setups hinder deployment; switching to standard helm charts recommended for easier scaling

### User Access Management
- Permission controls tested successfully
- Focus on resolving access issues for user role testing
- Multi-tenant user access through Web UI permission controls is advancing

### Community Tools Integration
- Exploring community-built tools to accelerate development and connect Open Web UI with MCP-compatible services
- Integration plans focus on connecting Open Web UI to existing MCP-compatible services like Trello, Notion, and Todoist

### Documentation
- A shared spreadsheet will log ongoing work and integration challenges, enhancing team coordination and visibility
- Documentation will prevent repeated roadblocks by sharing workarounds and integration insights

---

## Next Steps

1. Deploy shared MCP server environment
2. Enable robust user access controls
3. Integrate community tools for practical workflows
4. Continue working on user permissions, Docker stability, and Kubernetes deployments
5. Documentation of integration challenges and solutions

---

*Meeting facilitated by Lukas Herajt*
*Notes compiled: January 14, 2026*
