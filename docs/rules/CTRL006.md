# CTRL006 · Sandboxing not observed on an exec path

*An AI002 exec-class sink exists in this file, with no sandboxing construct
observed anywhere in it.*

- **Dimension:** operational control (assurance area 8: technical controls).
- **Severity:** low (review) · **Gates:** never.
- **Kind:** finding correlation. **Cadence:** one per agent candidate.

## Detection

Fires when the file already carries an **AI002** finding whose `variant` is
`exec` (model output reaching `eval`/`exec`/`subprocess.run`/`os.system`/
`child_process.exec`/etc. — see [AI002](AI002.md)), and no sandboxing
construct is observed anywhere in the file:

- A restricted environment passed to the subprocess call itself
  (`subprocess.run(..., env=...)`).
- Container/isolation tooling: `docker`, `nsjail`, `firejail`, `firecracker`,
  `gvisor`.
- Restricted interpreters: `RestrictedPython`, `isolated-vm`,
  `vm.createContext`/`vm.runInNewContext`.

CTRL006 only fires alongside an existing AI002 exec finding — it never fires
on its own. It answers a narrower question than AI002 does: not just *"can
model output reach exec,"* but *"if it does, is anything containing the
blast radius."*

## Vulnerable → remediated

```python
# FLAGGED — AI002 exec sink, no sandboxing construct anywhere in the file
resp = llm.invoke(prompt)
subprocess.run(resp.choices[0].message.content, shell=True)

# NOT FLAGGED — restricted environment passed to the call
resp = llm.invoke(prompt)
subprocess.run(resp.choices[0].message.content, shell=True, env={})
```

Suppress: `# stoa: ignore[CTRL006] reason`
