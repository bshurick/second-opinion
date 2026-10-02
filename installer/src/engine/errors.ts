/** A named failure. `message` says what failed; `hint` says the next step. */
export class InstallError extends Error {
  readonly hint: string;

  constructor(message: string, hint = "") {
    super(message);
    this.name = "InstallError";
    this.hint = hint;
  }

  /** One line for stderr: "what failed — next step". */
  format(): string {
    return this.hint ? `${this.message} — ${this.hint}` : this.message;
  }
}

/** Bad arguments (exit 2) as opposed to a failed step (exit 1). */
export class UsageError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UsageError";
  }
}
