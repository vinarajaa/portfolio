@app.route('/view_projects', methods=['GET', "POST"])
@login_required
def view_projects(current_user):
    """main URL for view_projects"""
    if request.method == "GET":
        return render_template("view_projects.html", session_id=request.args.get("session_id"), current_user = current_user, page_title="View Projects")
    else:
        return "please dont post..."
