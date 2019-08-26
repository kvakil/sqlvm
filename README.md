# SQLVM

SQLVM (Structured Query Language Virtual Machine) is a source-to-source
compilation system. It allows you to use `goto`-like constructs in MySQL,
allowing for easy imperative programming.

For example, say we have a table `ARRAY` as follows:

```sql
CREATE TABLE ARRAY (`id` int not null primary key, `n` int);
INSERT INTO ARRAY (`id`, `n`) VALUES (1, 1), (2, 3), (3, -5), (4, 8); 
```

Say we want to find the sum of squares of the `n` column.  We can write a
Jinja2 template which can then be transpiled with `sqlvm`:

```jinja2
{% sqlvm %}
{# We can set our variables (one statement per line). #}
@idx := 0
@accumulator := 0

{# As usual, parenthesis denote subqueries. #}
(SELECT @count := COUNT(*) FROM ARRAY)

{# Create a label we can jump to. #}
{{ label("loop_start") }}
@idx := @idx + 1
{# Pull element out using a subquery. #}
(SELECT @e := n FROM ARRAY WHERE id = @idx)

@accumulator := @accumulator + @e * @e
{# We can use the jump function to jump to a label. #}
IF(@idx = @count, {{ jump("done") }}, {{ jump("loop_start") }})

{{ label("done") }}
@out := CONVERT(@accumulator, CHAR)
{% endsqlvm %}
```

As you can see, SQLVM has labels and jumps, so it can do everything a "real"
programming language can.  

Running `python3 sqlvm.py` on the above code will give us this MySQL program.
Note the result is a single MySQL statement (no [stacked
queries](http://www.sqlinjection.net/stacked-queries/) needed).

```sql
SELECT o FROM (
    SELECT 0 v, '' o, 0 pc FROM (SELECT @pc:=0, @mem:='', @out:='') i UNION ALL
    SELECT v,
    CASE @pc
        WHEN 0 THEN @idx := 0
        WHEN 1 THEN @res := 0
        WHEN 2 THEN (SELECT @count := COUNT(*) FROM ARRAY)
        WHEN 3 THEN 0
        WHEN 4 THEN @idx := @idx + 1
        WHEN 5 THEN (SELECT @e := n FROM ARRAY WHERE id = @idx)
        WHEN 6 THEN @res := @res + @e * @e
        WHEN 7 THEN IF(@idx = @count, @pc := 8, @pc := 3)
        WHEN 8 THEN 0
        WHEN 9 THEN @out := CONVERT(@res,CHAR)
        WHEN 10 THEN 0
    ELSE @out END,
    @pc:=@pc+1
    FROM (SELECT (E0.v+E1.v+E2.v+E3.v+E4.v+E5.v+E6.v+E7.v) v FROM(SELECT 0 v UNION ALL SELECT 1 v) E0 CROSS JOIN (SELECT 0 v UNION ALL SELECT 2 v) E1 CROSS JOIN (SELECT 0 v UNION ALL SELECT 4 v) E2 CROSS JOIN (SELECT 0 v UNION ALL SELECT 8 v) E3 CROSS JOIN (SELECT 0 v UNION ALL SELECT 16 v) E4 CROSS JOIN (SELECT 0 v UNION ALL SELECT 32 v) E5 CROSS JOIN (SELECT 0 v UNION ALL SELECT 64 v) E6 CROSS JOIN (SELECT 0 v UNION ALL SELECT 128 v) E7 ORDER BY v) s) q ORDER BY v DESC LIMIT 1
```

(More details about the transpilation process are [available
below](#how-does-it-work).)

## FAQ

### Why does this exist?

This is a good question. After all, the above example can be very succinctly
expressed in pure SQL as `SELECT SUM(n * n) FROM ARRAY`.

I mainly created this for fun. Being able to do stuff like this might be useful
in security [Capture The
Flags](https://en.wikipedia.org/wiki/Capture_the_flag#Computer_security). With
an eye towards that, the generated SQL is a single statement suitable for
SQL injections.

### How does it work?

The pseudocode is basically this:

```c
/* the program counter (i.e., which statement we'll be executing) */
pc = 0;
/* the output of the program */
out = "";
while (true) {
    switch (pc) {
        case 0: /* statement 0 */; break;
        case 1: /* statement 1 */; break;
        case 2: /* statement 2 */; break;
        /* ... */
    }

    pc = pc + 1;
}
```

We can represent variables using MySQL's [User-Defined
Variables](https://dev.mysql.com/doc/refman/8.0/en/user-variables.html), and
the `switch ... case` construct can be done via MySQL's [case
expression](https://dev.mysql.com/doc/refman/8.0/en/control-flow-functions.html#operator_case).
In other words, we can write something like this:

```sql
@pc := 0, @out := ''
CASE @pc
    WHEN 0 THEN /* statement 0 */
    WHEN 1 THEN /* statement 1 */
    WHEN 2 THEN /* statement 2 */
    /* ... */
    ELSE @out
END
```

When `@pc` becomes large enough, the program stops executing statements and
just returns `@out` (which is our program "output").

The only problem is representing the `while (true)` construct, which doesn't
have a great MySQL analogy. We could do something with [Common Table
Expressions](https://dev.mysql.com/doc/refman/8.0/en/with.html) to get
recursion, but those (1) can't be used SQL injections and (2) don't work in the
5.X branch of MySQL.

So scratch `while (true)`, we'll settle for getting a really big `for` loop:

```diff
-while (true) {
+for (int i = 0; i < (big power of 2); i++) {
```

To get a "for loop" in MySQL, we'll create a table and iterate over it with a
`FROM` clause.  The easiest way to get a very large table is to [`CROSS
JOIN`](https://dev.mysql.com/doc/refman/8.0/en/join.html) a bunch of small
tables together--in particular, we join power of two tables together:

```sql
SELECT (E0.v+E1.v+E2.v+/* ... */) v FROM
    (SELECT 0 v UNION ALL SELECT 1 v) E0 CROSS JOIN
    (SELECT 0 v UNION ALL SELECT 2 v) E1 CROSS JOIN
    (SELECT 0 v UNION ALL SELECT 4 v) E2 CROSS JOIN
    /* ... */
ORDER BY v
```

Putting it together (and adding some initialization code) we get:
```sql
/* Select the output */
SELECT o FROM (
    SELECT 0 v, '' o, 0 pc FROM (SELECT @pc:=0, @mem:='', @out:='') i UNION ALL
    SELECT v,
    CASE @pc
        WHEN 0 THEN /* statement 0 */
        WHEN 1 THEN /* statement 1 */
        WHEN 2 THEN /* statement 2 */
        /* ... */
    ELSE @out END,
    @pc:=@pc+1
(SELECT (E0.v+E1.v+E2.v+/* ... */) v FROM
    (SELECT 0 v UNION ALL SELECT 1 v) E0 CROSS JOIN
    (SELECT 0 v UNION ALL SELECT 2 v) E1 CROSS JOIN
    (SELECT 0 v UNION ALL SELECT 4 v) E2 CROSS JOIN
    /* ... */
ORDER BY v) s) q
ORDER BY v DESC LIMIT 1 /* filter to select the "last" output */
```

And tada, we have a virtual machine!

Finally, there's a Jinja2 extension for ergonomics purposes.

### How can I use it?

You'll need Python 3.

    $ python3 -m pip install -r requirements.txt
    $ python3 sqlvm.py {input template file here}

### Does this work with other SQL variants?

Not really, but the necessary scaffolding is there--for example see
`languages/mysql.py`.

### Documentation? Test Cases?

Not really, but there's examples under [examples/](examples/).

### Is this production ready? It doesn't sound like it.

Yes, it absolutely is.

## Similar Projects

[ELVM](https://github.com/shinh/elvm/) can compile C-like code to SQLite. It's
not too hard to recreate these ideas in ELVM, but the resulting code is far
less efficient because it doesn't interface with MySQL functions.
