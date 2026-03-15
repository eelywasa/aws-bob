# Known Issues

## Invocation name clash on screen devices

**Symptom:** On Echo Show and other screen devices, saying "Alexa, ask brainy bob..." sometimes invokes a different skill called "Brainy" instead.

**Cause:** Alexa's NLU on screen devices resolves the invocation name ambiguously when two skills have similar names. The other skill ("Brainy") appears to take precedence.

**Fix:** Rename the invocation name in `skill-package/interactionModels/custom/en-GB.json` to something unique (e.g. "clever bob", "captain bob"). Requires a model rebuild via `ask smapi set-interaction-model`.

**Workaround:** Launch the skill from Skills & Games → Your Skills → Dev in the Alexa app.
