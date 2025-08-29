from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import EmailStr

conf = ConnectionConfig(
    MAIL_USERNAME="16853810p",
    MAIL_PASSWORD="Windowsopening2012*",
    MAIL_FROM=EmailStr("cfonseca@cnb.csic.es"),
    MAIL_PORT=587,
    MAIL_SERVER="smtpin.csic.es",
    USE_CREDENTIALS=True,
    TEMPLATE_FOLDER='/tmp'
)


async def sendVerificationEmail(recipient: str, code: str):
    message = MessageSchema(
        subject="Verify your email",
        recipients=[EmailStr(recipient)],
        body=f"Your verification code is: {code}",
        subtype='plain'
    )
    fm = FastMail(conf)
    await fm.send_message(message)
