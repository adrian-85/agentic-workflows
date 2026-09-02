"""Tailor Adrian Alan's master resume for CarMax - Principal Engineer, Quality.

Strong JD fit: AI/agentic testing, MCP-based agents, QE org leadership &
mentorship, test strategy, API/integration automation, shift-left, quality
metrics, bug triage, Playwright/NodeJS/TypeScript, C#/.NET/Azure.

Approved by user (seniority decision, SKILL Step 3):
  - Drop whole oldest roles Illumina (2012-2014) + Epic Sciences (2015) ->
    visible timeline becomes ~10.5 contiguous years (2016-2026), above the
    JD's "8+ years" ask. Record --seniority-approved at render.
  - Drop Education (BA is not evidence for this QE-Principal role).
Target 3 pages. Reallocates: keeps GEICO rich (the JD's best match),
compresses every older role, trims Tools lines, removes spacers.

Re-run from the untouched master:
    cd ~/.pi/agent/skills/resume-tailoring && python3 scripts/tailor_carmax_quality.py
"""

import shutil

from docx_edit import (
    load, save, paras, find_p, set_text, set_labeled,
    drop, drop_role, drop_section, remove_empty,
)

SRC = "Adrian Alan Master Resume.docx"
DST = "Adrian Alan Resume - CarMax Principal Quality.docx"


def main():
    shutil.copy(SRC, DST)
    root, body, names, data, _ = load(DST)
    ps = paras(body)

    # ------------------------------------------------------------------ #
    # SENIORITY ALIGNMENT + EDUCATION (approved): drop whole oldest roles in
    # a gapless tail block, and the Education section (degree not evidence).
    # ------------------------------------------------------------------ #
    ps = drop_role(body, "Illumina, San Diego")
    ps = drop_role(body, "Epic Sciences, San Diego")
    ps = drop_section(body, "Education")

    # ------------------------------------------------------------------ #
    # 1. SUMMARY — lead with QE leadership + AI-agentic testing + span.
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Results-driven Staff engineer"),
        "Staff Quality Engineer and AI-adoption leader with over 10 years "
        "architecting test automation and quality engineering strategy "
        "across payments, healthcare, and startup environments. Owns quality "
        "end-to-end: designs robust automation frameworks, drives shift-left "
        "methodologies, and engineers AI-augmented testing, including "
        "agentic workflows and MCP-based agents embedded directly into "
        "CI/CD. Leads and mentors engineering teams org-wide, defines "
        "testing standards and quality metrics for stakeholders, and "
        "accelerates release velocity. Deep experience in API and "
        "integration test automation across Java, TypeScript, C#/.NET, and "
        "Azure.",
    )

    # ------------------------------------------------------------------ #
    # 2. TECHNICAL PROFICIENCIES — JD-technologies lead; MCP/AI first.
    # ------------------------------------------------------------------ #
    set_labeled(
        find_p(ps, "Programming Languages: Java"),
        "Programming Languages: ",
        "TypeScript, JavaScript, C#, Java, Python, Go",
    )
    set_labeled(
        find_p(ps, "AI Tooling: Pi"),
        "AI Tooling: ",
        "MCP (Model Context Protocol), Agentic Workflows, Agentic SDLC, "
        "Claude, Copilot, OpenAI, Pi, OpenCode, Cursor, RAG pipelines, "
        "Self-healing Automation, Predictive Analytics",
    )
    set_labeled(
        find_p(ps, "Automation Testing Frameworks:"),
        "Automation Testing Frameworks: ",
        "Playwright, WebDriverIO, Cypress, Karate, Selenium, Gatling, Jest, "
        "TestNG, JUnit, Go testing",
    )
    set_labeled(
        find_p(ps, "CI/CD: Jenkins"),
        "CI/CD: ",
        "Azure DevOps, GitHub Actions, Jenkins, CircleCI, ArgoCD",
    )
    set_labeled(
        find_p(ps, "Version Control & Build Tools:"),
        "Version Control & Build Tools: ",
        "Git, GitHub, Bitbucket, Azure, Maven, npm, NuGet",
    )
    set_labeled(
        find_p(ps, "Databases: SQL Server"),
        "Databases: ",
        "SQL Server, PostgreSQL, MySQL, MongoDB",
    )
    set_labeled(
        find_p(ps, "API & Web Services: REST"),
        "API & Web Services: ",
        "REST, GraphQL, gRPC, Postman, JSON, XML, Kafka, Azure Service Bus",
    )
    set_labeled(
        find_p(ps, "Cloud & Containers: AWS"),
        "Cloud & Containers: ",
        "Azure, AWS, GCP, Docker, Kubernetes",
    )
    # Drop Artifact Management (JFrog) line — no JD evidence for this role.
    ps = drop(body, [
        "Artifa",
        "Monitoring",
    ])

    # ------------------------------------------------------------------ #
    # 3. SENIOR ROLE (GEICO) — re-anchor intro, keep the JD's best matches.
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Sole testing and quality engineering resource"),
        "Staff Engineer and sole test-automation and quality engineering "
        "resource for GEICO's entire Payments department, leading quality "
        "strategy across 5 engineering teams and 30 engineers building a "
        "new Payments platform. Drives the department's AI adoption and "
        "agentic testing innovation end-to-end.",
    )
    # Keep the strongest AI + release + test-framework bullets; drop the rest.
    ps = drop(body, [
        # release-support / process bullets (lower value for THIS JD)
        "Built a commit-diff library th",
        "Served as point of contact whe",
        "Demoed release process improve",
        "Engaged PaaS team to provide n",
        "Wrote scripts for creating, up",
        "Successfully advocated for onb",
        "Pioneered model-based testing ",
        "Migrated teams from Excel-base",
        "Implemented a native Go integr",
    ])
    # Trim the GEICO Tools line to one JD-focused line (was wrapping).
    set_labeled(
        find_p(ps, "Tools & Technologies: Go"),
        "Tools & Technologies: ",
        "Go, Python, TypeScript, JavaScript, Azure, Kubernetes, Docker, "
        "Claude, Copilot, OpenAI, OpenCode, Pi, MCP, GitHub, Grafana, "
        "K6",
    )

    # ------------------------------------------------------------------ #
    # 4. COMPRESS OLDER ROLES — keep 2-6 strongest, JD-aligned bullets each.
    # ------------------------------------------------------------------ #
    # Symbols (startup; keep automation-architecture + Playwright advising)
    ps = drop(body, [
        "Advised engineer working on th",
        "Created standardized engineeri",
    ])
    # Symbols: keep test-automation architecture intro, SDK test-data
    # setup, CI/CD pipelines (3 bullets — thin 5-month startup role).

    # CareMetx (SDET leadership, API/performance/Playwright/Chaos)
    ps = drop(body, [
        "Addressed high-priority compli",
        "Configured Snyk for team repos",
        "Co-architected JavaScript lint",
        "Started creating Terraform to ",
    ])

    # CVS Health (API, production automation, mentorship, SDLC)
    ps = drop(body, [
        "Proactively worked to remediat",
        "Authored runtime tests data cr",
        "Presented best practices for A",
    ])

    # Trove (end-to-end, Cypress, performance)
    ps = drop(body, [
        "Scripted Groovy-based Jenkins ",
        "Presented UI test framework us",
    ])

    # Republic Services (QA leadership, Karate, test data)
    ps = drop(body, [
        "Enhanced quality of API docume",
        "Refactored test cases and core",
    ])

    # Rakuten (API releases, framework, bug triage, integrations) — keep
    # the bug-scrub bullet (JD requires bug triage), drop coordination ones.
    ps = drop(body, [
        "Established bi-monthly interde",
        "Coordinated with cross-functio",
        "Asked to help with testing for",
    ])

    # ------------------------------------------------------------------ #
    # 5. TRIM OLDER Tools LINES to one line each (all wrapped).
    # ------------------------------------------------------------------ #
    trims = [
        ("Tools & Technologies: Go",
         "Tools & Technologies: ",
         "Go, TypeScript, JavaScript, Azure, Docker, Kubernetes, MCP, "
         "Claude, Copilot, OpenAI, OpenCode, Pi"),
        ("Tools & Technologies: GitHub C",
         "Tools & Technologies: ",
         "GitHub Copilot, GitHub Actions, JavaScript, Node, GCP"),
        ("Tools & Technologies: MVC",
         "Tools & Technologies: ",
         "C#, .NET, TypeScript, REST, GraphQL, AWS, Docker, Kubernetes, "
         "Playwright, Selenium, Karate"),
        ("Tools & Technologies: C#, .NET, Angular, REST, SQL",
         "Tools & Technologies: ",
         "C#, .NET, Angular, REST, SQL, Azure DevOps, Karate, Docker, "
         "Kubernetes"),
        ("Tools & Technologies: Node, Re",
         "Tools & Technologies: ",
         "Node, React, PostgreSQL, GraphQL, Cypress, JavaScript, Jest, "
         "Docker"),
        ("Tools & Technologies: Spring B",
         "Tools & Technologies: ",
         "Spring Boot, Java, SQL, Karate, JSON, Jenkins, GitHub"),
        ("Tools & Technologies: LAMP",
         "Tools & Technologies: ",
         "REST APIs, JSON, Java, Karate, Selenium, Python"),
    ]
    for prefix, label, value in trims:
        set_labeled(find_p(ps, prefix), label, value)

    # Drop the Payments cert — no JD evidence for this role (~1 line).
    ps = drop(body, ["Paymen"])

    # ------------------------------------------------------------------ #
    # 6. RECLAIM SPACE — drop blank inter-role spacers.
    # ------------------------------------------------------------------ #
    remove_empty(body)

    save(DST, root, names, data, src=SRC)
    print("WROTE", DST)


if __name__ == "__main__":
    main()