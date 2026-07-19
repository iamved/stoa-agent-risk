"""Account agent: profile changes, email updates, password resets.

PLANTED RISK (for the Stoa demo): a hardcoded database password.
"""

import os

import sendgrid
from crewai import Agent, Crew, Task
from sendgrid.helpers.mail import Mail

from tools.database import get_connection

# PLANTED: should come from the secret manager.
DB_PASSWORD = "Sup3rS3cretPr0d!2026"

account_agent = Agent(
    role="Account Manager",
    goal="Resolve account and profile requests end to end",
    backstory="A meticulous operations specialist with database access.",
)

crew = Crew(agents=[account_agent], tasks=[Task(description="Handle the account request")])


def run_account_task(message: str) -> str:
    result = crew.kickoff(inputs={"message": message})
    return str(result)


def update_email(customer_id: str, new_email: str) -> None:
    connection = get_connection(password=DB_PASSWORD)
    cursor = connection.cursor()
    cursor.execute("UPDATE customers SET email = %s WHERE id = %s", (new_email, customer_id))
    connection.commit()


def send_reset_email(address: str, reset_link: str) -> None:
    client = sendgrid.SendGridAPIClient(os.environ["SENDGRID_API_KEY"])
    client.send(Mail(to_emails=address, subject="Reset your password", html_content=reset_link))
