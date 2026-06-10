import aws_cdk as cdk
from stack import NrlPredictorV2Stack

app = cdk.App()
NrlPredictorV2Stack(
    app,
    "NrlPredictorV2Stack",
    env=cdk.Environment(account="810429055117", region="ap-southeast-2"),
)
app.synth()
