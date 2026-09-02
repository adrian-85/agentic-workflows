"""Tailor Adrian's master resume for BILL Senior SDET (fintech/payments).

JD selling points driven by the posting:
- Automation-first (~80%), AI-assisted test design/authoring.
- TypeScript/Playwright across UI and API (functional, contract, integration).
- Framework design, CI/CD quality gating, coverage expectations.
- Root-cause test failures; release criteria; coaching devs to own tests.
- Desired: payments experience, contract testing, observability (Datadog/Splunk).

User decisions this session:
- DROP Illumina (2012) and Epic (2015) as whole roles -> STRICTLY needs
  RESUME_VALIDATE_ARGS="--jd-years 5 --seniority-approved" at render time.
- API testing always included contract testing -> weave "contract" into the
  API-testing bullets (PaymentTech, CVS API suites, Expedia), never invent
  tool names (no Pact claim).
- Target 3 pages, keep the full remaining timeline.

Pass 1 = content edits + whole-role removals + tools trims + confident
off-theme drops. Pass 2 (after measure) = DROP PLAN bullet cuts.
"""

import shutil

from docx_edit import (
    load, save, paras, find_p, set_text, set_labeled, replace_text,
    merge_into, drop, remove, remove_empty,
)

SRC = "Adrian Alan Master Resume.docx"
DST = "Adrian Alan Resume - BILL SDET.docx"


def main():
    shutil.copy(SRC, DST)
    root, body, names, data, _ = load(DST)
    ps = paras(body)

    # ------------------------------------------------------------------ #
    # 1. WHOLE-ROLE REMOVALS (user-approved; seniority alignment)         #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        # Epic Sciences: header, title, bullets, tools
        "Epic Sciences, San Diego, CA",
        "Software Quality Assurance Eng",
        "Led QA for all assigned test p",
        "Cultivated data sets to verify",
        "Tools & Technologies: Bamboo,",
        # Illumina: header, title, bullets, tools
        "Illumina, San Diego, CA",
        "Software Test Engineer I",
        "Primary test engineer for Next",
        "Coordinated with internal IT t",
        "Proposed plan for continuous t",
        "Proposed generating mock data ",
        "Resource for testers in the de",
        "Sole tester for majority of as",
        "Developed test protocols, repo",
        "Served as tester for one of co",
        "Worked closely with internal q",
        "Tools & Technologies: MS Test,",
    ])

    # ------------------------------------------------------------------ #
    # 2. SUMMARY — lead with automation-first + AI-assisted + payments.  #
    #    No em dashes, double hyphens, or semicolons.                    #
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Results-driven Staff engineer "),
        "Automation-first SDET with 10+ years building test automation that "
        "anticipates defects, reduces code, and simplifies testing. Led AI "
        "adoption and built agentic workflows that author, maintain, and "
        "triage tests. Deep payments experience designing contract and "
        "integration test plans for payment authorization flows and sandbox "
        "validation, plus release processes across a 13-service platform. "
        "Skilled in TypeScript and Playwright across UI and API layers, "
        "CI/CD quality gating, coverage measurement, and root-cause analysis "
        "of test failures. Coaches engineers to own test authorship and holds "
        "a high bar for quality at every stage of development.",
    )

    # ------------------------------------------------------------------ #
    # 3. TECHNICAL PROFICIENCIES — JD-relevant tools lead.               #
    # ------------------------------------------------------------------ #
    set_labeled(
        find_p(ps, "Programming Languages: Java, C"),
        "Programming Languages: ",
        "TypeScript, JavaScript, Java, C#, Python, Go",
    )
    set_labeled(
        find_p(ps, "Automation Testing Frameworks:"),
        "Automation Testing Frameworks: ",
        "Playwright, Cypress, Karate, Gatling, Selenium, Jest, JUnit, TestNG",
    )

    # ------------------------------------------------------------------ #
    # 4. GEICO — re-anchor intro, weave contract testing, merge the two  #
    #    ASDLC bullets, drop off-theme bullets.                          #
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Sole testing and quality engin"),
        "Sole testing and quality engineering resource for GEICO's entire "
        "Payments department, reporting to the Director of Payments. "
        "Partnered with the director, her managers, and the head architect "
        "to drive quality practices, release processes, and testing changes "
        "across 5 engineering teams and 30 engineers building a new "
        "Payments platform.",
    )
    set_text(
        find_p(ps, "Designed test plan for Payment"),
        "Designed contract and integration test plans for the PaymentTech "
        "payment integration, validating the payment authorization flow and "
        "response codes, including triggering specific conditions by passing "
        "test codes to their sandbox environment.",
    )
    # Merge the two overlapping ASDLC bullets into one.
    keep = find_p(ps, "Developed a semi-autonomous ag")
    absorb = find_p(ps, "ASDLC integrations included Az")
    merge_into(
        body, keep, absorb,
        "Developed a semi-autonomous agentic workflow using sub-agents to "
        "improve unit testing and engineered an ASDLC (agentic software "
        "development life cycle) from ticket creation through pull-request "
        "comment resolution, integrating Azure CLI, GitHub CLI, SonarQube "
        "API, and Grafana tooling and authoring a reusable library for "
        "converting future MCP integrations to Pi-native extensions.",
    )
    # Merge the two Go coverage bullets (framework refactor + CI measurement
    # tool) into one to reclaim a line while keeping the coverage signal.
    keep = find_p(ps, "Refactored the existing Go int")
    absorb = find_p(ps, "Implemented a native Go integr")
    merge_into(
        body, keep, absorb,
        "Refactored the existing Go integration test framework, splitting "
        "thousand-line files into clearly named modules and replacing "
        "whitebox flows that skipped steps with test-equivalent "
        "functionality, increasing coverage by over 20%. Built a native Go "
        "measurement tool that ran in CI to report exactly how much code "
        "each run exercised.",
    )
    ps = drop(body, [
        "Co-presented with a fellow Sta",      # graceful-shutdown library
        "Built a commit-diff library th",      # release notes automation
        "Served as point of contact whe",      # corporate release reqs
        "Demoed release process improve",      # demo
        "Engaged PaaS team to provide n",      # Grafana dashboard
        "Configured OpenCode and Pi sec",      # AI guardrails (off-ask)
        "Migrated teams from Excel-base",      # Azure DevOps case migration
        "Wrote scripts for creating, updating, and storing",  # JFrog scripts
        "Successfully advocated for onboarding CI/CD",       # Paved Roads
    ])

    # ------------------------------------------------------------------ #
    # 5. CAREMETX — drop off-theme bullets.                             #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        "Migrated test cases across pro",      # Jira REST API migration
        "Started creating Terraform to",       # repo automation
    ])

    # ------------------------------------------------------------------ #
    # 6. CVS HEALTH — weave contract testing into the API suite bullet,  #
    #    drop generic/process bullets.                                   #
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Re-architected API test suites"),
        "Re-architected API test suites, including contract testing, for a "
        "CVS Health Medicare program that processed medical intake forms and "
        "health screenings, making them more readable, scalable, and "
        "significantly improving assertions.",
    )
    ps = drop(body, [
        "Authored runtime tests data cr",      # data script
        "Presented best practices for A",      # presentation
        "Led SDLC process improvements,",      # process standards
    ])

    # ------------------------------------------------------------------ #
    # 7. TROVE — drop the BDD presentation bullet.                       #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        "Presented UI test framework us",      # BDD presentation
    ])

    # ------------------------------------------------------------------ #
    # 8. REPUBLIC SERVICES — drop the API-docs bullet.                   #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        "Enhanced quality of API docume",      # API docs
    ])

    # ------------------------------------------------------------------ #
    # 9. RAKUTEN — weave contract testing into the Expedia bullet, drop  #
    #    the coordination/meeting bullets.                               #
    # ------------------------------------------------------------------ #
    set_text(
        find_p(ps, "Built integration tests for Ex"),
        "Built integration and contract tests for the Expedia travel API, "
        "reading Expedia's API documentation to ensure accurate and "
        "comprehensive test scenarios.",
    )
    ps = drop(body, [
        "Established bi-monthly interde",      # QA meetings
        "Coordinated with cross-functio",      # cross-team coordination
        "Asked to help with testing for",       # mobile initiative
        "Oversaw migration of API test framework",# Karate framework migration
        "Led testing efforts for API project releases", # AWS cloud migration
        "Expedited a backlog of hundreds of defects",  # backlog scrub
    ])

    # ------------------------------------------------------------------ #
    # 9b. REPUBLIC SERVICES — keep the quantified smoke-stability and     #
    #     code-volume bullets, drop the rest (human override on scorer). #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        "Served as a subject matter exp",      # Karate SME
        "Pioneered migration to dynamic test data",  # dynamic test data
    ])

    # ------------------------------------------------------------------ #
    # 9c. TROVE — drop the generic e2e-approach bullet.                  #
    # ------------------------------------------------------------------ #
    ps = drop(body, [
        "Established a comprehensive test automation approach",  # e2e approach
    ])

    # ------------------------------------------------------------------ #
    # 10. TOOLS-LINE TRIMS — one line each, JD-relevant tools lead.      #
    # ------------------------------------------------------------------ #
    trims = [
        ("Tools & Technologies: Go, Pyth",
         "Tools & Technologies: ",
         "Go, TypeScript, Python, Kubernetes, Temporal, GitHub, Grafana, "
         "K6, Pi, OpenCode"),
        ("Tools & Technologies: GitHub C",
         "Tools & Technologies: ",
         "GitHub Actions, GitHub Codespaces, JavaScript, Node, "
         "Google Cloud Platform (GCP)"),
        ("Tools & Technologies: MVC",
         "Tools & Technologies: ",
         "TypeScript, JavaScript, Playwright, Jest, REST, GraphQL, AWS, Kafka"),
        ("Tools & Technologies: C#,",
         "Tools & Technologies: ",
         "C#, .NET, REST APIs, SQL, Kafka, Kubernetes, Karate, Azure DevOps"),
        ("Tools & Technologies: Node, Re",
         "Tools & Technologies: ",
         "Cypress, JavaScript, Jest, Node, GraphQL, PostgreSQL, Docker, "
         "Jenkins, Git"),
        ("Tools & Technologies: Spring B",
         "Tools & Technologies: ",
         "Spring Boot, Java, Karate, SQL, Gatling, Jenkins, GitHub, Git"),
        ("Tools & Technologies: LAMP (Li",
         "Tools & Technologies: ",
         "Java, Karate, REST APIs, Python, PyTest, Datadog, Selenium, "
         "Git, GitHub"),
    ]
    for prefix, label, value in trims:
        set_labeled(find_p(ps, prefix), label, value)

    # ------------------------------------------------------------------ #
    # 11. GRAMMAR / CASING FIXES on kept bullets (master nits).           #
    # ------------------------------------------------------------------ #
    fixes = [
        # Official/compound casing
        ("Designed the Payments release ", "13 service distributed", "13-service distributed"),
        ("Co-architected JavaScript lint", "using Circle CI and JFrog", "using CircleCI and JFrog"),
        ("Pioneered test automation exec", "HIPAA regulated environment", "HIPAA-regulated environment"),
        ("Configured CI/CD pipelines to ", "cross dependency changes", "cross-dependency changes"),
        # Missing articles / clipped grammar
        ("Led team of SDETs in developin", "Led team of SDETs", "Led a team of SDETs"),
        ("Managed quality assurance team", "Managed quality assurance team for", "Managed a quality assurance team for"),
        ("Mentored junior team member re", "Mentored junior team member", "Mentored a junior team member"),
        ("Pushed for and obtained a week", "Built automated weekly release pipeline", "Built an automated weekly release pipeline"),
        ("Championed the adoption of Cyp", "co-architecting initial framework", "co-architecting the initial framework"),
        # Missing terminal period
        ("Refactored test cases and core", "reducing code volume by 75%", "reducing code volume by 75%."),
        # De-duplicate the "Go integration test framework" phrase shared with
        # the merged Go bullet (validator near-dup warning).
        ("Engaged the internal QnD test-",
         "building a new Go-based integration test framework backed by an internally developed reporting dashboard",
         "building a new Go-based integration framework backed by an internally developed reporting dashboard"),
    ]
    for prefix, old, new in fixes:
        replace_text(find_p(ps, prefix), old, new)

    # ------------------------------------------------------------------ #
    # 12. CLEANUP — blank spacers, then save.                            #
    # ------------------------------------------------------------------ #
    remove_empty(body)

    save(DST, root, names, data, src=SRC)
    print("WROTE", DST)


if __name__ == "__main__":
    main()