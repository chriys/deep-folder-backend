 # TODO

- [x] ~~*Set up Sandcastle*~~
- [x] Pick project: Talk to a folder MVP

## Starting prompt - backend
Create the backend of an interface, where a user should be able to authenticate a GSuite account, which should be used to give google drive access.
Then, a user should be able to copy and paste any link from Google Drive into the interface, which should kick off an agent conversation.
This agent should be able to answer any questions about any of the files in the folder. 
These are the must have features:
- Multi-file reasoning (agent explicitly reasons across documents)
    * cross-document comparisons (“compare Q3 vs Q4 docs”)
    * synthesis mode (“summarize all files in this folder into themes”)
    * contradiction detection (“these two docs disagree—why?”)
- Better citations (page/section level):
    * page-level citations (PDF page numbers)
    * paragraph-level anchors
    * clickable deep links into Drive file sections
- Folder ingestion + sync:
    * instead of links ingest entire folders
    * Keep Drive and your index in sync:
    * detect file edits
    * re-embed only changed chunks
- Hybrid search
    * combine vector search and keyword search (BM25-style)
- Semantic folder indexing
    * Instead of indexing files individually:
        * build a “folder-level embedding”
        * allows high-level navigation (“what is this folder about?”)
- Task mode (“summarize / extract / compare”)
    * Instead of chat:
        * “Extract all action items from these docs”
        * “Build a meeting summary”

