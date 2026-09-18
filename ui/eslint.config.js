import js from "@eslint/js";
import tseslint from "typescript-eslint";

// The report is a security artifact: no string from the envelope may ever be
// rendered as HTML. Both React's escape hatch and the raw DOM property are
// banned outright, and there is no per-line opt-out convention.
export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "Banned: render envelope strings as text nodes only." },
        { selector: "MemberExpression[property.name='innerHTML']", message: "Banned: render envelope strings as text nodes only." },
        { selector: "MemberExpression[property.name='outerHTML']", message: "Banned: render envelope strings as text nodes only." },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "Banned: render envelope strings as text nodes only." },
        { selector: "CallExpression[callee.property.name='write'][callee.object.name='document']", message: "Banned: document.write." },
      ],
    },
  },
);
