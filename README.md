- pipeline贯穿：async+fastapi+sqlite+agent layer。
    > #insight hot loading: agent layer, fast api layer，and db layer. key build up philosophy: 
        1.detach each layer, so you can hot plugin, for example try to not use framework stuff for fastapi and db layer, so next time if change to other agent framework you can normal work.
        2. 快速原型，每个模块先基本骨架连通，再去具体填充内容。

- 解耦好agent layer，fast api router，以及db layer

- client.py

- 跑通；但是context management这里出现问题。

- 并发读写db已正常。

[] 选择切换数据库，或者增加其他的tools，或者已完成
