## Description: <br>
Assists with Chinese long-form fiction planning and drafting, including characters, world building, outlines, chapter generation, style control, and plot-thread tracking. <br>

This skill is ready for commercial/non-commercial use. <br>

## Publisher: <br>
[hanbinsite](https://clawhub.ai/user/hanbinsite) <br>

### License/Terms of Use: <br>
MIT-0 <br>


## Use Case: <br>
Writers and agent users use this skill to organize a novel project, maintain character and world state, draft or regenerate chapters through a configured LLM endpoint, and export outlines or progress statistics. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Novel drafts, character notes, world details, and chapter outlines are saved locally and may be sent to the configured LLM endpoint during generation. <br>
Mitigation: Use a trusted endpoint, verify NOVEL_API_BASE_URL, use a dedicated API key, and avoid confidential manuscript material unless the provider is approved for that content. <br>
Risk: The security summary flags review-evasion wording in the writing requirements. <br>
Mitigation: Remove or revise review-evasion wording before using the skill in publication or platform-compliance workflows. <br>
Risk: The package needs clearer privacy notice for remote generation. <br>
Mitigation: Document what project data is stored locally and what prompt content is sent to the configured LLM provider before deployment. <br>


## Reference(s): <br>
- [ClawHub skill page](https://clawhub.ai/hanbinsite/my-novel-writer) <br>
- [README](artifact/README.md) <br>
- [Resource overview](artifact/RESOURCE_OVERVIEW.md) <br>
- [Novel structure guide](artifact/guides/novel_structure_guide.md) <br>
- [Chapter outline template](artifact/templates/chapter_outline.md) <br>
- [Character card template](artifact/templates/character_card.md) <br>
- [World building template](artifact/templates/world_building.md) <br>


## Skill Output: <br>
**Output Type(s):** [text, markdown, code, shell commands, configuration, guidance] <br>
**Output Format:** [Markdown files, JSON project state, plain-text chapter content, CLI commands, and configuration guidance.] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [Writes local novel project files under WORKDIR/novels and sends generation prompts to the configured LLM endpoint.] <br>

## Skill Version(s): <br>
1.0.0 (source: server release metadata) <br>

## Ethical Considerations: <br>
Users should evaluate whether this skill is appropriate for their environment, review any generated or modified files before relying on them, and apply their organization's safety, security, and compliance requirements before deployment. <br>
