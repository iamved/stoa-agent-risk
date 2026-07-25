# DECL003 · Money-moving or contract-signing permission with no declared economic authority

*This agent can move funds, approve transactions, or sign contracts, but
`stoa-declared.toml` has no `economic_authority` for it.*

- **Severity:** high · **Gates:** yes.
- **Kind:** contradiction (declared vs. scanned). **Cadence:** once per agent.

## Detection

Fires when an agent has the `move_funds`, `approve_transactions`, or
`sign_contracts` [permission tag](../declarations.md) (Stripe/PayPal/Plaid/
Adyen transfer or capture patterns; DocuSign/Dropbox Sign/Adobe Sign), and no
`economic_authority` block is declared for it at all — regardless of whether
the agent has any other declaration. An undeclared money-moving agent is
itself the gap this rule names.

Independent of [DECL002](DECL002.md): DECL002 is "you declared a limit but
didn't enforce it"; DECL003 is "you never declared a limit in the first
place."

## Fix

Add an `[agents."<id>".economic_authority]` block declaring the real limits
this agent operates under.

Suppress: `# stoa: ignore[DECL003] reason`
