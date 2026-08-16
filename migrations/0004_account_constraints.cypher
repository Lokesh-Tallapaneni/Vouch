// Accounts are separate from people: most people in the graph never sign up.
// The email constraint is what makes "register" safe under concurrency --
// two simultaneous sign-ups with the same address cannot both succeed.
CREATE CONSTRAINT account_id IF NOT EXISTS
  FOR (a:Account) REQUIRE a.id IS UNIQUE;

CREATE CONSTRAINT account_email IF NOT EXISTS
  FOR (a:Account) REQUIRE a.email IS UNIQUE;
