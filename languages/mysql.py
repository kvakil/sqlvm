from jinja2 import environmentfilter

pc = None
labels = None
lg_steps = 8

PROLOGUE = """SELECT o FROM (
    SELECT 0 v, '' o, 0 pc FROM (SELECT @pc:=0, @mem:='', @out:='') i UNION ALL
    SELECT v,
    CASE @pc"""


def prologue():
    """Called automatically when starting a SQLVM block."""
    global pc, labels, lg_steps
    pc = -1
    labels = {}
    return PROLOGUE


def exit():
    """"Exits" a program."""
    # Right now, we don't know what the maximum PC will be. We create a thunk,
    # which we evaluate to the maximum PC in the second pass.
    return "{{ _exit_thunk() }}"


def _exit_thunk():
    return "@pc:={}".format(pc)


def set_lg_steps(my_lg_steps):
    """Set the (log base two) of the number of "steps" the program will execute
    for. See _generate_steps_table for details."""
    global lg_steps
    lg_steps = my_lg_steps
    return ""


def _generate_steps_table():
    return "".join(
        (
            "(SELECT (",
            "+".join("E{}.v".format(i) for i in range(lg_steps)),
            ") v FROM",
            " CROSS JOIN ".join(
                "(SELECT 0 v UNION ALL SELECT {exp} v) E{i}".format(exp=2 ** i, i=i)
                for i in range(lg_steps)
            ),
            " ORDER BY v) s",
        )
    )


def label(name):
    """Associates the given label with the current PC."""
    if name in labels:
        raise ValueError("duplicate label {}".format(name))
    labels[name] = pc
    # We output 0, since labels are used as statements and all statements must
    # output something.
    return "0"


def jump(name):
    """Jumps to a label."""
    # Since the label may not yet be defined, this is actually a thunk. SQLVM
    # then interprets this thunk in a second pass, where it will actually point
    # to the label.
    return '{{ _jump_thunk("' + name + '") }}'


def _jump_thunk(name):
    return "@pc:={}".format(labels.get(name, name))


def alloc(amt):
    """Allocates more "memory", as used by load and store below."""
    return "@mem:=CONCAT(@mem,REPEAT('<m></m>',{}))".format(amt)


def load(dst, src):
    """Load the contents of the memory address SRC into the variable DST."""
    if isinstance(src, str) and src.startswith("@"):
        src = "$" + src
    # TODO: handle < and > in memory
    return "{dst}:=ExtractValue(@mem,'/m[{src}]')".format(dst=dst, src=src)


def store(src, dst):
    """Store the literal or variable DST at the memory address SRC."""
    if isinstance(dst, str) and dst.startswith("@"):
        dst = "$" + dst
    # TODO: handle < and > in memory
    tag = "CONCAT('<m>',{src},'</m>')".format(src=src)
    return "@mem:=UpdateXML(@mem,'/m[{dst}]',{tag})".format(dst=dst, tag=tag)


def statement():
    """Called automatically in between SQLVM statements, or manually by Jinja2
    templating code."""
    global pc
    pc += 1
    return "\n        WHEN {} THEN ".format(pc)


def nop():
    """Statement which does nothing."""
    return "0"


EPILOGUE = """0
    ELSE @out END,
    @pc:=@pc+1
    FROM {steps_table}) q ORDER BY v DESC LIMIT 1"""


def epilogue():
    """Called automatically when ending a SQLVM block."""
    return EPILOGUE.format(steps_table=_generate_steps_table())
