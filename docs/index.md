# Ravel
Ravel is a general-purpose Python application framework that lets you focus on what's important from the get-go, without burning out or getting sidetracked by databases, user interface libraries or network communication protocols. It builds upon tried and true patterns for scaling, extending and maintaining applications without sacrificing efficiency or simplicity.

The development process in Ravel is designed to mirror the natural evolution of ideas, from notes scrawled on a piece of paper to a full-fledged microservice architecture, offering a handful of nifty tools to facilitate debugging and testing.

## A Quick Example
Let's begin by taking a quick look at what it takes to spin up a new, minimal Ravel app in two steps: defining a domain model and a high-level application interface.

### The Domain Model
Our example domain model consists of _users_ and _accounts_. Each account is _owned_ by a single user but associated with many _member_ users. For more information on domain modeling with Ravel, see [Business Objects](./business-layer/index.md).

```python
# file: example.py

from ravel import Resource, Relationship
from ravel.schema import Field, Email, String


class Account(Resource):
  members = Relationship(lambda self: User.account_id == self._id, many=True)
  owner = Relationship(lambda self: User._id == self.owner_id)
  owner_id = Field(private=True, required=True)


class User(Resource):
  account = Relationship(lambda self: Account._id == self.account_id)
  account_id = Field(private=True, required=True)
  password = String(private=True)
  email = Email()
```

### The Application Interface
In Ravel, an application interface is simply a collection of functions, registered with a user interface library or web framework
via decorator. See [Application Interface Layer](./interface-layer/index.md) for details.

In our example, we will register the same two functions `signup` and `login` functions for use in both a JSON web server and interactive IPython shell, or REPL.

```python
from ravel.app.repl import ReplApplication
from ravel.app.web.http_server import HttpServerApplication

repl = ReplApplication()
http = HttpServerApplication()


@repl()
@http(url_path='/signup', http_method='POST')
def signup(email, password):
  owner = User(email=email.lower(), password=password).save()
  owner.account = Account(owner_id=owner._id).save()
  return owner.save()


@repl()
@http(url_path='/login', http_method='POST')
def login(email, password):
  user = User.query(User.email == email.lower(), first=True)
  if user and user.password == password:
    return user
  else:
    # TODO: raise NotAuthorized()
    return None
```

At this point, we can start the application in a REPL by running the following code:
```python
import sys

from example import repl, http


app = sys.argv[1]

if app == 'http':
  app = http
elif app == 'repl':
  app = repl

app.manifest.process()
app.start()
```

Note that the app is now fully functional, without the need for a database or ORM. We can lauch the app as a JSON web service or REPL.

```sh
# start an IPython session with API functions built-in.
python example.py repl

# start the app as a JSON API web server.
python example.py http
```

In the REPL, you can try something like this:

```python
account = signup('foo@bar.baz', 'password')
user = login('foo@bar.baz', 'password')

assert user == account.owner
```
