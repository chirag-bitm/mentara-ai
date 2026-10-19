import { rmSync } from "node:fs";
import { spawnSync } from "node:child_process";


const outputDirectory = ".test-dist";

function runNode(arguments_) {
  return spawnSync(process.execPath, arguments_, {
    cwd: process.cwd(),
    stdio: "inherit",
  }).status ?? 1;
}

let exitCode = 1;

try {
  const compileExitCode = runNode([
    "node_modules/typescript/bin/tsc",
    "-p",
    "tsconfig.reducer-tests.json",
  ]);

  if (compileExitCode === 0) {
    exitCode = runNode([
      "--test",
      `${outputDirectory}/tests/reconnect-policy.test.js`,
      `${outputDirectory}/tests/answer-reducer.test.js`,
      `${outputDirectory}/tests/conversation-reducer.test.js`,
      `${outputDirectory}/tests/prediction-reducer.test.js`,
      `${outputDirectory}/tests/transcript-reducer.test.js`,
    ]);
  }
} finally {
  rmSync(outputDirectory, { recursive: true, force: true });
}

process.exit(exitCode);
