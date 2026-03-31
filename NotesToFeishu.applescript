on run
    set sel to {}
    tell application "Notes"
        set sel to selection
    end tell

    if sel is {} then
        tell me to activate
        display alert "请先在 Apple Notes 中选中一篇笔记，再运行此程序。" as warning
        return
    end if

    tell application "Notes"
        set theNote to item 1 of sel
        set noteTitle to name of theNote
        set noteHTML to body of theNote
    end tell

    do shell script "echo " & quoted form of noteHTML & " | /usr/bin/python3 /Users/boyu/Projects/note-to-feishu/note_to_feishu.py " & quoted form of noteTitle & " >> /tmp/notes_to_feishu.log 2>&1"

    display notification "飞书文档已创建：" & noteTitle with title "同步到飞书"
end run
