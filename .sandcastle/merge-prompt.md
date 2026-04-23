# TASK

Merge the following branches into the current branch and keep the original Dockerfile, *.md, *.mts files  .sandcastle/ folder:

{{BRANCHES}}

For each branch:

1. Run `git merge <branch> --no-edit`
2. If there are merge conflicts, resolve them intelligently by reading both sides and choosing the correct resolution
3. After resolving conflicts, run `npm run typecheck` and `npm run test` to verify everything works
4. If tests fail, fix the issues before proceeding to the next branch

After all branches are merged, make a single commit summarizing the merge prefixing it with `RALPH: <model>:`. Where `<model>` is the name of the model used. Then delete the branches you have merged.

# CLOSE ISSUES

For each issue listed below, close it using:

`gh issue close <id> --comment "Completed by Sandcastle"`

where `<id>` is the issue ID from the list.

{{ISSUES}}

Once you've merged everything you can, output <promise>COMPLETE</promise>.
