## What this changes

<!-- One or two sentences. What is different after this merges? -->

## Why

<!-- The problem it solves. Link the issue if there is one. CONTRIBUTING asks
     for an issue first, so that discussion is usually the best link. -->

## How it was checked

<!-- Not "tests pass". What did you run, and what did you see? If it changes a
     number, say which number and how you confirmed the new one is right. -->

- [ ] `uv run pytest` passes locally
- [ ] `npm --prefix web run lint` and `npm --prefix web run build` pass
- [ ] No golden number under `sample_data/golden/` was changed, or if one was,
      a person worked it out by hand and the reasoning is in the description
- [ ] The core library still imports without web or forecast dependencies
- [ ] An ADR is added if this closes off an alternative someone could
      reasonably have picked
